using System;
using System.IO;
using System.Collections.Generic;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Threading;

using IronPython.Hosting;
using IronPython.Runtime;
using IronPython.Runtime.Operations;

using Microsoft.Scripting;
using Microsoft.Scripting.Hosting;

using Ironclad.Structs;

namespace Ironclad
{

    public enum UnmanagedDataMarker
    {
        PyStringObject,
        PyTupleObject,
        PyListObject,
        None,
    }

    public class BadRefCountException : Exception
    {
        public BadRefCountException(string message): base(message)
        {
        }
    }

    public class CannotInterpretException : Exception
    {
        public CannotInterpretException(string message): base(message)
        {
        }
    }

    internal delegate void ActualiseDelegate(IntPtr typePtr);

    public partial class Python25Mapper : Python25Api, IDisposable
    {
        private ScriptEngine engine;
        private StubReference stub;
        private PydImporter importer;
        private IAllocator allocator;

        private ScriptScope scratchModule;
        private ScriptScope dispatcherModule;
        private object dispatcherClass;
        private object dispatcherLock;

        private bool alive = false;
        private InterestingPtrMap map = new InterestingPtrMap();
        private Dictionary<IntPtr, ActualiseDelegate> actualisableTypes = new Dictionary<IntPtr, ActualiseDelegate>();
        private Dictionary<IntPtr, object> actualiseHelpers = new Dictionary<IntPtr, object>();
        private Dictionary<IntPtr, List> listsBeingActualised = new Dictionary<IntPtr, List>();
        private Dictionary<string, IntPtr> internedStrings = new Dictionary<string, IntPtr>();
        private Dictionary<IntPtr, IntPtr> FILEs = new Dictionary<IntPtr, IntPtr>();
        private List<IntPtr> tempObjects = new List<IntPtr>();

        private LocalDataStoreSlot threadDictStore = Thread.AllocateDataSlot();
        private LocalDataStoreSlot threadGILStore = Thread.AllocateDataSlot();
        // TODO: this should probably be thread-local too
        private object _lastException = null;

        // one day, perhaps, this 'set' will be empty
        private StupidSet unknownNames = new StupidSet();

        // TODO: must be a better way to handle imports...
        private string importName = "";
        
        public Python25Mapper() : this(null, Python.CreateEngine(), new HGlobalAllocator())
        {
        }

        public Python25Mapper(string stubPath) : this(stubPath, Python.CreateEngine(), new HGlobalAllocator())
        {
        }

        public Python25Mapper(IAllocator alloc) : this(null, Python.CreateEngine(), alloc)
        {
        }

        public Python25Mapper(string stubPath, ScriptEngine inEngine, IAllocator alloc)
        {
            this.engine = inEngine;
            this.allocator = alloc;
            this.AddPaths();
            this.CreateDispatcherModule();
            this.CreateScratchModule();
            if (stubPath != null)
            {
                this.stub = new StubReference(stubPath);
                this.stub.Init(new AddressGetterDelegate(this.GetAddress), new DataSetterDelegate(this.SetData));
                this.ReadyBuiltinTypes();
                this.importer = new PydImporter();
                
                // TODO: work out why this line causes leakage
                this.ExecInModule(CodeSnippets.INSTALL_IMPORT_HOOK_CODE, this.scratchModule);
            }
            this.alive = true;
        }
        
        
        private void AddPaths()
        {
            List<string> paths = new List<string>();
            string rootPath = Assembly.GetExecutingAssembly().Location;
            paths.Add(Directory.GetParent(rootPath).FullName);

            string ipyPath = Environment.GetEnvironmentVariable("IRONPYTHONPATH");
            if (ipyPath != null && ipyPath.Length > 0)
            {
                string[] ipyPaths = ipyPath.Split(Path.PathSeparator);
                foreach (string p in ipyPaths) 
                {
                    paths.Add(p);
                }
            }
            
            this.engine.SetSearchPaths(paths.ToArray());
        }
        
        
        private void DumpPtr(IntPtr ptr)
        {
            if (!this.allocator.Contains(ptr))
            {
                return;
            }
            GC.SuppressFinalize(this.Retrieve(ptr));
            IntPtr typePtr = CPyMarshal.ReadPtrField(ptr, typeof(PyObject), "ob_type");
            CPython_destructor_Delegate dgt = (CPython_destructor_Delegate)
                CPyMarshal.ReadFunctionPtrField(
                    typePtr, typeof(PyTypeObject), "tp_dealloc", typeof(CPython_destructor_Delegate));
            dgt(ptr);
        }
        
        protected virtual void Dispose(bool disposing)
        {
            lock (this.dispatcherLock)
            {
                if (this.alive)
                {
                    this.map.MapOverBridgePtrs(new PtrFunc(this.DumpPtr));
                    this.StopDispatchingDeletes();
                    this.alive = false;
                    this.allocator.FreeAll();
                    foreach (IntPtr FILE in this.FILEs.Values)
                    {
                        Unmanaged.fclose(FILE);
                    }
                    if (this.stub != null)
                    {
                        this.importer.Dispose();
                        this.stub.Dispose();
                    }
                }
            }
        }
        
        public void Dispose()
        {
            this.Dispose(true);
            GC.SuppressFinalize(this);
        }

        public bool
        Alive
        {
            get { return this.alive; }
        }

        public ScriptEngine
        Engine
        {
            get
            {
                return this.engine;
            }
        }
        
        public IntPtr 
        Store(object obj)
        {
            if (obj != null && obj.GetType() == typeof(UnmanagedDataMarker))
            {
                throw new ArgumentTypeException("UnmanagedDataMarkers should not be stored by clients.");
            }
            if (obj == null)
            {
                this.IncRef(this._Py_NoneStruct);
                return this._Py_NoneStruct;
            }
            if (this.map.HasObj(obj))
            {
                IntPtr ptr = this.map.GetPtr(obj);
                this.IncRef(ptr);
                GC.KeepAlive(obj); // please test me, if you can work out how to
                return ptr;
            }
            return this.StoreDispatch(obj);
        }
        
        
        private IntPtr
        StoreObject(object obj)
        {
            IntPtr ptr = this.allocator.Alloc(Marshal.SizeOf(typeof(PyObject)));
            CPyMarshal.WriteIntField(ptr, typeof(PyObject), "ob_refcnt", 1);
            CPyMarshal.WritePtrField(ptr, typeof(PyObject), "ob_type", this.PyBaseObject_Type);
            this.map.Associate(ptr, obj);
            return ptr;
        }
        
        
        public void
        StoreBridge(IntPtr ptr, object obj)
        {
            this.map.BridgeAssociate(ptr, obj);
        }
        
        
        public bool
        HasPtr(IntPtr ptr)
        {
            return this.map.HasPtr(ptr);
        }
        

        private void
        AttemptToMap(IntPtr ptr)
        {
            if (this.map.HasPtr(ptr))
            {
                return;
            }

            if (ptr == IntPtr.Zero)
            {
                throw new CannotInterpretException(
                    String.Format("cannot map IntPtr.Zero"));
            }

            IntPtr typePtr = CPyMarshal.ReadPtrField(ptr, typeof(PyTypeObject), "ob_type");
            this.AttemptToMap(typePtr);

            if (!this.actualisableTypes.ContainsKey(typePtr))
            {
                throw new CannotInterpretException(
                    String.Format("cannot map object at {0} with type at {1}", ptr.ToString("x"), typePtr.ToString("x")));
            }
            this.actualisableTypes[typePtr](ptr);
        }

        
        public object 
        Retrieve(IntPtr ptr)
        {
            this.AttemptToMap(ptr);
            if (this.map.HasPtr(ptr))
            {
                object possibleMarker = this.map.GetObj(ptr);
                if (possibleMarker.GetType() == typeof(UnmanagedDataMarker))
                {
                    UnmanagedDataMarker marker = (UnmanagedDataMarker)possibleMarker;
                    switch (marker)
                    {
                        case UnmanagedDataMarker.None:
                            return null;

                        case UnmanagedDataMarker.PyStringObject:
                            this.ActualiseString(ptr);
                            break;

                        case UnmanagedDataMarker.PyTupleObject:
                            this.ActualiseTuple(ptr);
                            break;

                        case UnmanagedDataMarker.PyListObject:
                            ActualiseList(ptr);
                            break;

                        default:
                            throw new Exception("Found impossible data in pointer map");
                    }
                }
            }
            return this.map.GetObj(ptr);
        }

        public int 
        RefCount(IntPtr ptr)
        {
            this.AttemptToMap(ptr);
            if (this.map.HasPtr(ptr))
            {
                this.map.UpdateStrength(ptr);
                int count = CPyMarshal.ReadIntField(ptr, typeof(PyObject), "ob_refcnt");
                return count;
            }
            else
            {
                throw new KeyNotFoundException(String.Format(
                    "RefCount: missing key in pointer map: {0}", ptr));
            }
        }
        
        public void 
        IncRef(IntPtr ptr)
        {
            this.AttemptToMap(ptr);
            if (this.map.HasPtr(ptr))
            {
                int count = CPyMarshal.ReadIntField(ptr, typeof(PyObject), "ob_refcnt");
                CPyMarshal.WriteIntField(ptr, typeof(PyObject), "ob_refcnt", count + 1);
                this.map.UpdateStrength(ptr);
            }
            else
            {
                throw new KeyNotFoundException(String.Format(
                    "IncRef: missing key in pointer map: {0}", ptr));
            }
        }
        
        public void 
        DecRef(IntPtr ptr)
        {
            this.AttemptToMap(ptr);
            if (this.map.HasPtr(ptr))
            {
                int count = CPyMarshal.ReadIntField(ptr, typeof(PyObject), "ob_refcnt");
                if (count == 0)
                {
                    throw new BadRefCountException("Trying to DecRef an object with ref count 0");
                }

                if (count == 1)
                {
                    IntPtr typePtr = CPyMarshal.ReadPtrField(ptr, typeof(PyObject), "ob_type");

                    if (typePtr != IntPtr.Zero)
                    {
                        if (CPyMarshal.ReadPtrField(typePtr, typeof(PyTypeObject), "tp_dealloc") != IntPtr.Zero)
                        {
                            CPython_destructor_Delegate deallocDgt = (CPython_destructor_Delegate)
                                CPyMarshal.ReadFunctionPtrField(
                                    typePtr, typeof(PyTypeObject), "tp_dealloc", typeof(CPython_destructor_Delegate));
                            deallocDgt(ptr);
                            return;
                        }
                    }
                    // TODO: remove this get-out-of-jail-free, and ensure that 
                    // all the types I create actually have dealloc functions
                    this.PyObject_Free(ptr);
                }
                else
                {
                    CPyMarshal.WriteIntField(ptr, typeof(PyObject), "ob_refcnt", count - 1);
                    this.map.UpdateStrength(ptr);
                }
            }
            else
            {
                throw new KeyNotFoundException(String.Format(
                    "DecRef: missing key in pointer map: {0}", ptr));
            }
        }
        
        public void 
        Strengthen(object obj)
        {
            this.map.Strengthen(obj);
        }
        
        public void 
        Weaken(object obj)
        {
            this.map.Weaken(obj);
        }

        public void
        CheckBridgePtrs()
        {
            this.map.CheckBridgePtrs();
        }
        
        public override void 
        PyObject_Free(IntPtr ptr)
        {
            if (this.FILEs.ContainsKey(ptr))
            {
                Unmanaged.fclose(this.FILEs[ptr]);
                this.FILEs.Remove(ptr);
            }
            this.Unmap(ptr);
            this.allocator.Free(ptr);
        }

        public void Unmap(IntPtr ptr)
        {
            // TODO: very badly tested (nothing works if this isn't here, but...)
            if (this.map.HasPtr(ptr))
            {
                this.map.Release(ptr);
            }
        }

        public void RememberTempObject(IntPtr ptr)
        {
            this.tempObjects.Add(ptr);
        }

        public void FreeTemps()
        {
            foreach (IntPtr ptr in this.tempObjects)
            {
                this.DecRef(ptr);
            }
            this.tempObjects.Clear();
        }
        
        
        public override IntPtr 
        GetAddress(string name)
        {
            IntPtr result = base.GetAddress(name);
            if (result != IntPtr.Zero)
            {
                return result;
            }

            switch (name)
            {
                case "PyBaseObject_Dealloc":
                    this.dgtMap[name] = new CPython_destructor_Delegate(this.PyBaseObject_Dealloc);
                    break;
                case "PyBaseObject_Init":
                    this.dgtMap[name] = new CPython_initproc_Delegate(this.PyBaseObject_Init);
                    break;
                case "PyTuple_Dealloc":
                    this.dgtMap[name] = new CPython_destructor_Delegate(this.PyTuple_Dealloc);
                    break;
                case "PySlice_Dealloc":
                    this.dgtMap[name] = new CPython_destructor_Delegate(this.PySlice_Dealloc);
                    break;
                case "PyList_Dealloc":
                    this.dgtMap[name] = new CPython_destructor_Delegate(this.PyList_Dealloc);
                    break;
                case "PyCObject_Dealloc":
                    this.dgtMap[name] = new CPython_destructor_Delegate(this.PyCObject_Dealloc);
                    break;
                
                default:
                    this.unknownNames.Add(name);
                    return IntPtr.Zero;
            }
            return Marshal.GetFunctionPointerForDelegate(this.dgtMap[name]);
        }
        
        
        public override int
        PyCallable_Check(IntPtr objPtr)
        {
            if (Builtin.callable(DefaultContext.Default, this.Retrieve(objPtr)))
            {
                return 1;
            }
            return 0;
        }
        
        
        public override void
        Fill__Py_NoneStruct(IntPtr address)
        {
            PyObject none = new PyObject();
            none.ob_refcnt = 1;
            none.ob_type = this.PyNone_Type;
            Marshal.StructureToPtr(none, address, false);
            this.map.Associate(address, UnmanagedDataMarker.None);
        }

        public override void
        Fill__Py_ZeroStruct(IntPtr address)
        {
            PyIntObject False = new PyIntObject();
            False.ob_refcnt = 1;
            False.ob_type = this.PyBool_Type;
            False.ob_ival = 0;
            Marshal.StructureToPtr(False, address, false);
            this.map.Associate(address, false);
        }

        public override void
        Fill__Py_TrueStruct(IntPtr address)
        {
            PyIntObject True = new PyIntObject();
            True.ob_refcnt = 1;
            True.ob_type = this.PyBool_Type;
            True.ob_ival = 1;
            Marshal.StructureToPtr(True, address, false);
            this.map.Associate(address, true);
        }

        public override void
        Fill__Py_EllipsisObject(IntPtr address)
        {
            PyObject ellipsis = new PyObject();
            ellipsis.ob_refcnt = 1;
            ellipsis.ob_type = this.PyEllipsis_Type;
            Marshal.StructureToPtr(ellipsis, address, false);
            this.map.Associate(address, Builtin.Ellipsis);
        }
        
        
        public override void
        Fill_Py_OptimizeFlag(IntPtr address)
        {
            CPyMarshal.WriteInt(address, 2);
        }
        
    }

}
