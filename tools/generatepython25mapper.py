
import os
from utils import read_interesting_lines

def writefile(name, text):
    f = open(name, "w")
    try:
        f.write("/* This file was generated by tools/generatepython25mapper.py */")
        f.write(FILE_TEMPLATE % text)
    finally:
        f.close()

def foreversplit(line):
    for part in line.split():
        yield part
    while True:
        yield ''

def mapstrings(names, infile, template):
    extract = lambda line: template % dict(zip(names, foreversplit(line)))
    return map(extract, read_interesting_lines(infile))

def run():
    exc_snippets = mapstrings(("name",), EXCEPTIONS_INFILE, EXCEPTION_TEMPLATE)
    writefile(EXCEPTIONS_OUTFILE, "\n\n".join(exc_snippets))
    
    store_snippets = mapstrings(("type",), STORE_INFILE, STORE_TYPE_TEMPLATE)
    store_code = STORE_METHOD_TEMPLATE % "\n".join(store_snippets)
    writefile(STORE_OUTFILE, store_code)
    
    operator_snippets = mapstrings(("name", "operator"), OPERATOR_INFILE, OPERATOR_TEMPLATE)
    writefile(OPERATOR_OUTFILE, "\n\n".join(operator_snippets))
    
    c2py_snippets = mapstrings(("name", "type", "cast"), C2PY_INFILE, C2PY_TEMPLATE)
    writefile(C2PY_OUTFILE, "\n\n".join(c2py_snippets))
    
    py2c_snippets = mapstrings(("name", "converter", "type", "default", "coerce"), PY2C_INFILE, PY2C_TEMPLATE)
    writefile(PY2C_OUTFILE, "\n\n".join(py2c_snippets))
    
    fill_types_snippets = []
    for line in read_interesting_lines(FILL_TYPES_INFILE):
        _input = line.split(None, 2)
        _dict = dict(name=_input[0], type=_input[1])
        
        _extra_snippets = []
        if len(_input) > 2:
            _extra = eval(_input[-1])
            for (k, v) in sorted(_extra.items()):
                if k == "tp_as_number":
                    _extra_snippets.append(FILL_TYPES_AS_NUMBER_TEMPLATE % v)
                elif k in ("tp_basicsize", "tp_itemsize"):
                    _extra_snippets.append(FILL_TYPES_SIZE_TEMPLATE % (k, v))
                else:
                    _extra_snippets.append(FILL_TYPES_GETADDRESS_TEMPLATE % (k, v))
        _dict["extra"] = '\n'.join(_extra_snippets)
        
        fill_types_snippets.append(FILL_TYPES_TEMPLATE % _dict)
    writefile(FILL_TYPES_OUTFILE, "\n\n".join(fill_types_snippets))
    
    
    

EXCEPTIONS_INFILE = "exceptions"
EXCEPTIONS_OUTFILE = "../Python25Mapper_exceptions.Generated.cs"
STORE_INFILE = "store_dispatch"
STORE_OUTFILE = "../Python25Mapper_store_dispatch.Generated.cs"
OPERATOR_INFILE = "operator"
OPERATOR_OUTFILE = "../Python25mapper_operator.Generated.cs"
C2PY_INFILE = "numbers_convert_c2py"
C2PY_OUTFILE = "../Python25mapper_numbers_convert_c2py.Generated.cs"
PY2C_INFILE = "numbers_convert_py2c"
PY2C_OUTFILE = "../Python25mapper_numbers_convert_py2c.Generated.cs"
FILL_TYPES_INFILE = "fill_types"
FILL_TYPES_OUTFILE = "../Python25mapper_fill_types.Generated.cs"

FILE_TEMPLATE = """
using System;
using System.Collections;
using System.Runtime.InteropServices;
using IronPython.Modules;
using IronPython.Runtime;
using IronPython.Runtime.Exceptions;
using IronPython.Runtime.Operations;
using IronPython.Runtime.Types;
using Microsoft.Scripting.Math;
using Ironclad.Structs;

namespace Ironclad
{
    public partial class Python25Mapper : Python25Api
    {
%s
    }
}
"""

EXCEPTION_TEMPLATE = """\
        public override void Fill_PyExc_%(name)s(IntPtr addr)
        {
            IntPtr value = this.Store(PythonExceptions.%(name)s);
            CPyMarshal.WritePtr(addr, value);
        }"""

STORE_METHOD_TEMPLATE = """\
        private IntPtr StoreDispatch(object obj)
        {
%s
            return this.StoreObject(obj);
        }"""

STORE_TYPE_TEMPLATE = """\
            if (obj is %(type)s) { return this.Store((%(type)s)obj); }"""

OPERATOR_TEMPLATE = """\
        public override IntPtr
        %(name)s(IntPtr arg1ptr, IntPtr arg2ptr)
        {
            try
            {
                object result = PythonOperator.%(operator)s(this.scratchContext, this.Retrieve(arg1ptr), this.Retrieve(arg2ptr));
                return this.Store(result);
            }
            catch (Exception e)
            {
                this.LastException = e;
                return IntPtr.Zero;
            }
        }"""

C2PY_TEMPLATE = """\
        public override IntPtr
        %(name)s(%(type)s value)
        {
            return this.Store(%(cast)svalue);
        }"""

PY2C_TEMPLATE = """\
        public override %(type)s
        %(name)s(IntPtr valuePtr)
        {
            try
            {
                return this.%(converter)s(this.Retrieve(valuePtr))%(coerce)s;
            }
            catch (Exception e)
            {
                this.LastException = e;
                return %(default)s;
            }
        }"""

FILL_TYPES_TEMPLATE = """\
        public override void
        Fill_%(name)s(IntPtr ptr)
        {
            CPyMarshal.Zero(ptr, Marshal.SizeOf(typeof(PyTypeObject)));
            CPyMarshal.WriteIntField(ptr, typeof(PyTypeObject), "ob_refcnt", 1);
%(extra)s
            this.map.Associate(ptr, %(type)s);
        }"""

FILL_TYPES_AS_NUMBER_TEMPLATE = """\
            this.%s(ptr);"""

FILL_TYPES_SIZE_TEMPLATE = """\
            CPyMarshal.WriteIntField(ptr, typeof(PyTypeObject), "%s", Marshal.SizeOf(typeof(%s)));"""

FILL_TYPES_GETADDRESS_TEMPLATE = """\
            CPyMarshal.WritePtrField(ptr, typeof(PyTypeObject), "%s", this.GetAddress("%s"));"""

if __name__ == "__main__":
    run()



