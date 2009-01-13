

FILE_TEMPLATE = """\
using System;
using System.Runtime.InteropServices;

using IronPython.Runtime;
using IronPython.Runtime.Exceptions;
using IronPython.Runtime.Operations;

namespace Ironclad
{
%s
}
"""

DISPATCHER_TEMPLATE = """
    public partial class Dispatcher
    {
%s
    }"""

METHOD_TEMPLATE = """\
        %(signature)s
        {
            this.mapper.EnsureGIL();
            try
            {
%(translate_objs)s
                %(store_ret)s%(call)s
%(cleanup_objs)s
                %(handle_ret)s
                PythonExceptions.BaseException error = (PythonExceptions.BaseException)this.mapper.LastException;
                if (error != null)
                {
                    this.mapper.LastException = null;
                    throw error.clsException;
                }
                %(return_ret)s
            }
            finally
            {
                this.mapper.ReleaseGIL();
            }
        }
"""
SIGNATURE_TEMPLATE = "public %(rettype)s %(name)s(%(arglist)s)"
CALL_TEMPLATE = "((dgt_%(dgttype)s)(this.table[key]))(%(arglist)s);"

TRANSLATE_OBJ_TEMPLATE = """\
                IntPtr ptr%(index)d = this.mapper.Store(arg%(index)d);"""
TRANSLATE_NULLABLEKWARGS_TEMPLATE = """\
                IntPtr ptr%(index)d = IntPtr.Zero;
                if (Builtin.len(arg%(index)d) > 0)
                {
                    ptr%(index)d = this.mapper.Store(arg%(index)d);
                }"""

CLEANUP_OBJ_TEMPLATE = """\
                if (ptr%(index)d != IntPtr.Zero)
                {
                    this.mapper.DecRef(ptr%(index)d);
                }"""

FIELD_TEMPLATE = """\
        public %(cstype)s get_%(name)s_field(object instance, int offset)
        {
            this.mapper.EnsureGIL();
            try
            {
                IntPtr instancePtr = this.mapper.Store(instance);
                IntPtr address = CPyMarshal.Offset(instancePtr, offset);
                %(cstype)s ret = %(gettweak)s(CPyMarshal.Read%(cpmtype)s(address));
                this.mapper.DecRef(instancePtr);
                return ret;
            }
            finally
            {
                this.mapper.ReleaseGIL();
            }
        }
        public void set_%(name)s_field(object instance, int offset, %(cstype)s value)
        {
            this.mapper.EnsureGIL();
            try
            {
                IntPtr instancePtr = this.mapper.Store(instance);
                IntPtr address = CPyMarshal.Offset(instancePtr, offset);
                CPyMarshal.Write%(cpmtype)s(address, %(settweak)s(value));
                this.mapper.DecRef(instancePtr);
            }
            finally
            {
                this.mapper.ReleaseGIL();
            }
        }
"""

DGTTYPE_TEMPLATE = """\
    [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
    public delegate %(rettype)s dgt_%(name)s(%(arglist)s);
"""


HANDLE_RET_NULL = """object ret = null;
                if (retptr == IntPtr.Zero)
                {
                    if (this.mapper.LastException == null)
                    {
                        this.mapper.LastException = %s;
                    }
                }
                else
                {
                    ret = this.mapper.Retrieve(retptr);
                    this.mapper.DecRef(retptr);
                }"""

DEFAULT_HANDLE_RETPTR = HANDLE_RET_NULL % 'new NullReferenceException(key)'
ITERNEXT_HANDLE_RETPTR = HANDLE_RET_NULL % 'PythonOps.StopIteration()'
                
THROW_RET_NEGATIVE = """if (ret < 0)
                {
                    if (this.mapper.LastException == null)
                    {
                        this.mapper.LastException = new Exception(key);
                    }
                }"""

HANDLE_RET_DESTRUCTOR = """this.mapper.DecRef(ptr0);
                this.mapper.Unmap(ptr0);"""



MAGICMETHODS_TEMPLATE = """\
    public class MagicMethods
    {
        public static void
        GetInfo(string field, out string name, out string template, out Type dgtType, out bool needGetSwappedInfo)
        {
            needGetSwappedInfo = false;
            switch (field)
            {
%s
                default:
                    throw new NotImplementedException(String.Format("unrecognised field: {0}", field));
            }
        }
        
        public static void
        GetSwappedInfo(string field, out string name, out string template, out Type dgtType)
        {
            switch (field)
            {
%s
                default:
                    throw new NotImplementedException(String.Format("unrecognised field: {0}", field));
            }
        }
    }
"""


MAGIC_METHOD_CASE = """\
                case "%s":
                    name = "%s";
                    template = @"%s";
                    dgtType = typeof(dgt_%s);
                    %s
                    break;"""

MAGICMETHOD_TEMPLATE_TEMPLATE = """
def {0}(%(arglist)s):
    '''{1}'''
    return _0._dispatcher.%(functype)s('{2}{0}', %(callargs)s)
_ironclad_class_attrs['{0}'] = {0}"""

POW_TEMPLATE_TEMPLATE = """
def {0}(self, other, modulo=None):
    '''{1}'''
    return self._dispatcher.%(functype)s('{2}{0}', self, other, modulo)
_ironclad_class_attrs['{0}'] = {0}"""

POW_SWAPPED_TEMPLATE_TEMPLATE = """
def {0}(self, other):
    '''{1}'''
    return self._dispatcher.%(functype)s('{2}{0}', other, self, None)
_ironclad_class_attrs['{0}'] = {0}"""

SQUISHKWARGS_TEMPLATE_TEMPLATE = """
def {0}(self, *args, **kwargs):
    '''{1}'''
    return self._dispatcher.%(functype)s('{2}{0}', self, args, kwargs)
_ironclad_class_attrs['{0}'] = {0}"""
