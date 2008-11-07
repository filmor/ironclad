
from tests.utils.runtest import makesuite, run
from tests.utils.testcase import TestCase, WithMapper
from tests.utils.gc import gcwait

from System import IntPtr
from System.Reflection import BindingFlags
from System.Threading import AutoResetEvent, Thread, ThreadStart


def GetGIL(mapper):    
    _gilField = mapper.GetType().GetMember(
        "GIL", BindingFlags.NonPublic | BindingFlags.Instance)[0];
    return _gilField.GetValue(mapper);


class PyThread_functions_Test(TestCase):

    @WithMapper
    def testAllocateAndFreeLocks(self, mapper, _):
        lockPtr1 = mapper.PyThread_allocate_lock()
        lockPtr2 = mapper.PyThread_allocate_lock()

        self.assertNotEquals(lockPtr1, lockPtr2, "bad, wrong")

        lockObject1 = mapper.Retrieve(lockPtr1)
        lockObject2 = mapper.Retrieve(lockPtr2)

        self.assertNotEquals(lockObject1, lockObject2, "bad, wrong")

        mapper.PyThread_free_lock(lockPtr1)
        mapper.PyThread_free_lock(lockPtr2)  


    @WithMapper
    def testAcquireAndReleaseLocksWithWait(self, mapper, _):
        lockPtr1 = mapper.PyThread_allocate_lock()
        lockPtr2 = mapper.PyThread_allocate_lock()

        self.assertEquals(mapper.PyThread_acquire_lock(lockPtr1, 1), 1, "claimed failure")
        self.assertEquals(mapper.PyThread_acquire_lock(lockPtr2, 1), 1, "claimed failure")

        acquired = set()
        def AcquireLock(ptr):
            self.assertEquals(mapper.PyThread_acquire_lock(ptr, 1), 1, "claimed failure")
            acquired.add(ptr)
            mapper.PyThread_release_lock(ptr)

        t1 = Thread(ThreadStart(lambda: AcquireLock(lockPtr1)))
        t2 = Thread(ThreadStart(lambda: AcquireLock(lockPtr2)))
        t1.Start()
        t2.Start()
        Thread.CurrentThread.Join(100)

        self.assertEquals(acquired, set(), "not properly locked")

        mapper.PyThread_release_lock(lockPtr1)
        Thread.CurrentThread.Join(100)
        self.assertEquals(acquired, set([lockPtr1]), "release failed")

        mapper.PyThread_release_lock(lockPtr2)
        Thread.CurrentThread.Join(100)
        self.assertEquals(acquired, set([lockPtr1, lockPtr2]), "release failed")    


    @WithMapper
    def testAcquireAndReleaseLocksWithNoWait(self, mapper, _):
        lockPtr1 = mapper.PyThread_allocate_lock()
        lockPtr2 = mapper.PyThread_allocate_lock()

        self.assertEquals(mapper.PyThread_acquire_lock(lockPtr1, 1), 1, "claimed failure")
        self.assertEquals(mapper.PyThread_acquire_lock(lockPtr2, 1), 1, "claimed failure")

        failedToAcquire = set()
        def FailToAcquireLock(ptr):
            self.assertEquals(mapper.PyThread_acquire_lock(ptr, 0), 0, "claimed success")
            failedToAcquire.add(ptr)

        t1 = Thread(ThreadStart(lambda: FailToAcquireLock(lockPtr1)))
        t2 = Thread(ThreadStart(lambda: FailToAcquireLock(lockPtr2)))
        t1.Start()
        t2.Start()
        Thread.CurrentThread.Join(100)

        self.assertEquals(failedToAcquire, set([lockPtr1, lockPtr2]), "failed")

        mapper.PyThread_release_lock(lockPtr1)
        mapper.PyThread_release_lock(lockPtr2)

        acquired = set()
        def AcquireLock(ptr):
            self.assertEquals(mapper.PyThread_acquire_lock(ptr, 0), 1, "claimed failure")
            acquired.add(ptr)
            mapper.PyThread_release_lock(ptr)

        t1 = Thread(ThreadStart(lambda: AcquireLock(lockPtr1)))
        t2 = Thread(ThreadStart(lambda: AcquireLock(lockPtr2)))
        t1.Start()
        t2.Start()
        Thread.CurrentThread.Join(100)

        self.assertEquals(acquired, set([lockPtr1, lockPtr2]), "acquires failed")    

    
    @WithMapper
    def testMultipleAcquireSameThread(self, mapper, _):
        # these locks are apparently not meant to be recursive
        lockPtr = mapper.PyThread_allocate_lock()
        self.assertEquals(mapper.PyThread_acquire_lock(lockPtr, 1), 1, "claimed failure")
        self.assertEquals(mapper.PyThread_acquire_lock(lockPtr, 1), 0, "claimed success")
        mapper.PyThread_release_lock(lockPtr)
        
        lock = mapper.Retrieve(lockPtr)
        self.assertEquals(lock.IsAcquired, False)
        

class PyThreadStateDict_Test(TestCase):
    
    @WithMapper
    def testPyThreadState_GetDict(self, mapper, _):
        store = {}
        def GrabThreadDict(key):
            ptr = mapper.PyThreadState_GetDict()
            mapper.IncRef(ptr)
            local = mapper.Retrieve(ptr)
            local['content'] = key
            store[key] = local
            store[key + 'ptr'] = ptr
        
        GrabThreadDict('main')
        for name in ('other', 'another', 'and another'):
            thread = Thread(ThreadStart(lambda: GrabThreadDict(name)))
            thread.Start()
            thread.Join()
        
        gcwait()
        self.assertEquals(store['main']['content'], 'main')
        self.assertEquals(mapper.RefCount(store['mainptr']), 2, 'lost reference to dict while thread still active')
        
        for name in ('other', 'another', 'and another'):
            self.assertEquals(store[name]['content'], name)
            self.assertEquals(mapper.RefCount(store[name + 'ptr']), 1, 'failed to dispose of thread dicts when threads ended')


class PyThreadExceptionTest(TestCase):
    
    @WithMapper
    def testLastExceptionIsThreadLocal(self, mapper, _):
        def CheckOtherThread():
            self.assertEquals(mapper.LastException, None)
            mapper.LastException = ValueError('foo')
            self.assertEquals(isinstance(mapper.LastException, ValueError), True)

        mapper.LastException = TypeError('bar')
        thread = Thread(ThreadStart(CheckOtherThread))
        thread.Start()
        thread.Join()
        self.assertEquals(isinstance(mapper.LastException, TypeError), True)


class PyEvalGILThreadTest(TestCase):


    @WithMapper
    def testMultipleSaveRestoreOneThread(self, mapper, _):
        lock = GetGIL(mapper)
        
        mapper.PyGILState_Ensure()
        self.assertEquals(lock.IsAcquired, True)
        mapper.PyEval_SaveThread()
        self.assertEquals(lock.IsAcquired, False)
        mapper.PyEval_SaveThread()
        self.assertEquals(lock.IsAcquired, False)
        mapper.PyEval_RestoreThread(IntPtr.Zero)
        self.assertEquals(lock.IsAcquired, False)
        mapper.PyEval_RestoreThread(IntPtr.Zero)
        self.assertEquals(lock.IsAcquired, True)
        self.assertRaises(Exception, mapper.PyEval_RestoreThread)
        mapper.PyGILState_Release(0)

    
    @WithMapper
    def testMultipleSaveRestoreMultiThread(self, mapper, _):       # order of execution (intended)
        lock = GetGIL(mapper)
    
        oneThreadActed = AutoResetEvent(False)
        anotherThreadActed = AutoResetEvent(False)
        
        def OneThread():
            wait = lambda: anotherThreadActed.WaitOne()
            signal = lambda: oneThreadActed.Set()
            
            mapper.PyGILState_Ensure()                  # 1
            signal(); wait()
            
            pe_token = mapper.PyEval_SaveThread()       # 3
            self.assertNotEquals(pe_token, IntPtr.Zero)
            signal(); wait()
            
            self.assertFalse(lock.TryAcquire())         # 5
            signal(); wait()
            
            self.assertTrue(lock.TryAcquire())          # 7
            lock.Release()
            signal(); wait()
            
            self.assertTrue(lock.TryAcquire())          # 9
            lock.Release()
            signal(); wait()
            
            self.assertTrue(lock.TryAcquire())          # 11
            lock.Release()
            signal(); wait()
            
            self.assertFalse(lock.TryAcquire())         # 13
            signal(); wait()
            
            mapper.PyEval_RestoreThread(pe_token)       # 15
            signal(); wait()
            
            mapper.PyGILState_Release(0)                # 17

        def AnotherThread():
            wait = lambda: oneThreadActed.WaitOne()
            signal = lambda: anotherThreadActed.Set()
            wait()
            
            self.assertFalse(lock.TryAcquire())         # 2
            signal(); wait()
            
            mapper.PyGILState_Ensure()                  # 4
            signal(); wait()
            
            pe_token = mapper.PyEval_SaveThread()       # 6
            self.assertNotEquals(pe_token, IntPtr.Zero)
            signal(); wait()
            
            x = mapper.PyEval_SaveThread()              # 8
            self.assertEquals(x, IntPtr.Zero)
            signal(); wait()
            
            mapper.PyEval_RestoreThread(x)              # 10
            signal(); wait()
            
            mapper.PyEval_RestoreThread(pe_token)       # 12
            signal(); wait()
            
            mapper.PyGILState_Release(0)                # 14
            signal(); wait()
            
            self.assertFalse(lock.TryAcquire())         # 16
            signal()
            
        t = Thread(ThreadStart(AnotherThread))
        t.Start()
        OneThread()
        t.Join()
    
        mapper.Dispose()


suite = makesuite(
    PyThread_functions_Test,
    PyThreadStateDict_Test,
    PyThreadExceptionTest,
    PyEvalGILThreadTest,
)

if __name__ == '__main__':
    run(suite)
