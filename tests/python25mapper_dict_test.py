
import unittest
from tests.utils.runtest import makesuite, run

from tests.utils.allocators import GetAllocatingTestAllocator
from tests.utils.memory import CreateTypes

from System import IntPtr
from System.Runtime.InteropServices import Marshal

from Ironclad import CPyMarshal, Python25Mapper
from Ironclad.Structs import PyObject, PyTypeObject




class Python25MapperDictTest(unittest.TestCase):

    def testPyDict_New(self):
        allocs = []
        frees = []
        mapper = Python25Mapper(GetAllocatingTestAllocator(allocs, frees))
        deallocTypes = CreateTypes(mapper)
    
        dictPtr = mapper.PyDict_New()
        self.assertEquals(mapper.RefCount(dictPtr), 1, "bad refcount")
        self.assertEquals(allocs, [(dictPtr, Marshal.SizeOf(PyObject))], "did not allocate as expected")
        self.assertEquals(CPyMarshal.ReadPtrField(dictPtr, PyObject, "ob_type"), mapper.PyDict_Type, "wrong type")
        dictObj = mapper.Retrieve(dictPtr)
        self.assertEquals(dictObj, {}, "retrieved unexpected value")
        
        mapper.DecRef(dictPtr)
        self.assertRaises(KeyError, lambda: mapper.RefCount(dictPtr))
        self.assertEquals(frees, [dictPtr], "did not release memory")
        
        deallocTypes()


    def testPyDict_Size(self):
        mapper = Python25Mapper()
        deallocTypes = CreateTypes(mapper)
        dict0 = mapper.Store({})
        dict3 = mapper.Store({1:2, 3:4, 5:6})
        
        self.assertEquals(mapper.PyDict_Size(dict0), 0, "wrong")
        self.assertEquals(mapper.PyDict_Size(dict3), 3, "wrong")
        
        deallocTypes()


    def testPyDict_GetItemStringSuccess(self):
        mapper = Python25Mapper()
        deallocTypes = CreateTypes(mapper)
        dictPtr = mapper.Store({"abcde": 12345})
        
        itemPtr = mapper.PyDict_GetItemString(dictPtr, "abcde")
        self.assertEquals(mapper.Retrieve(itemPtr), 12345, "failed to get item")
        self.assertEquals(mapper.RefCount(itemPtr), 1, "something is wrong")
        mapper.FreeTemps()
        self.assertRaises(KeyError, lambda: mapper.RefCount(itemPtr))
        
        mapper.DecRef(dictPtr)
        deallocTypes()


    def testPyDict_GetItemStringFailure(self):
        mapper = Python25Mapper()
        deallocTypes = CreateTypes(mapper)
        dictPtr = mapper.Store({"abcde": 12345})
        
        itemPtr = mapper.PyDict_GetItemString(dictPtr, "bwahahaha!")
        self.assertEquals(itemPtr, IntPtr.Zero, "bad return for missing key")
        self.assertEquals(mapper.LastException, None, "should not set exception")
        
        mapper.DecRef(dictPtr)
        deallocTypes()
        

    def testStoreDictCreatesDictType(self):
        mapper = Python25Mapper()
        typeBlock = Marshal.AllocHGlobal(Marshal.SizeOf(PyTypeObject))
        mapper.SetData("PyDict_Type", typeBlock)
        
        dictPtr = mapper.Store({0: 1, 2: 3})
        self.assertEquals(CPyMarshal.ReadPtrField(dictPtr, PyObject, "ob_type"), typeBlock, "wrong type")
        
        mapper.DecRef(dictPtr)
        Marshal.FreeHGlobal(typeBlock)


suite = makesuite(
    Python25MapperDictTest,
)

if __name__ == '__main__':
    run(suite)