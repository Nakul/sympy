"""
This is our testing framework.

Goals:

* it should behave very similar (or identical) to py.test
* doesn't require any external dependencies
* preferably all the functionality should be in this file only
* no magic, just import the test file and execute the test functions, that's it
* portable

"""
import os
import sys
import inspect
import traceback
from glob import glob
from timeit import default_timer as clock

def isgeneratorfunction(object):
    """
    Return true if the object is a user-defined generator function.

    Generator function objects provides same attributes as functions.

    See isfunction.__doc__ for attributes listing.

    Adapted from Python 2.6.
    """
    CO_GENERATOR = 0x20
    if (inspect.isfunction(object) or inspect.ismethod(object)) and \
        object.func_code.co_flags & CO_GENERATOR:
        return True
    return False

def test(*paths, **kwargs):
    """
    Runs the tests specified by paths, or all tests if paths=[].

    Note: paths are specified relative to the sympy root directory in a unix
    format (on all platforms including windows).

    Examples:

    Run all tests:
    >> import sympy
    >> sympy.test()

    Run one file:
    >> import sympy
    >> sympy.test("sympy/core/tests/test_basic.py")

    Run all tests in sympy/functions/ and some particular file:
    >> import sympy
    >> sympy.test("sympy/core/tests/test_basic.py", "sympy/functions")
    """
    if "verbose" in kwargs:
        verbose = kwargs["verbose"]
    else:
        verbose = False
    r = PyTestReporter(verbose)
    t = SymPyTests(r)
    if len(paths) > 0:
        t.add_paths(paths)
    else:
        t.add_paths(["sympy"])
    return t.test()

class SymPyTests(object):

    def __init__(self, reporter):
        self._count = 0
        self._root_dir = self.get_sympy_dir()
        self._reporter = reporter
        self._reporter.root_dir(self._root_dir)
        self._tests = []

    def add_paths(self, paths):
        for path in paths:
            path2 = os.path.join(self._root_dir, *path.split("/"))
            if path2.endswith(".py"):
                self._tests.append(path2)
            else:
                self._tests.extend(self.get_tests(path2))

    def test(self):
        """
        Runs the tests.

        Returns True if all tests pass, otherwise False.
        """
        self._reporter.start()
        for f in self._tests:
            try:
                self.test_file(f)
            except KeyboardInterrupt:
                print " interrupted by user"
                break
        return self._reporter.finish()

    def test_file(self, filename):
        import sympy
        import imp
        name = "test%d" % self._count
        name = os.path.splitext(os.path.basename(filename))[0]
        self._count += 1
        try:
            #module = __import__(filename, globals(), locals())
            module = imp.load_source(name, filename)
        except ImportError:
            self._reporter.import_error(filename, sys.exc_info())
            return
        disabled = getattr(module, "disabled", False)
        if disabled:
            funcs = []
        else:
            funcs = sorted(module.__dict__.keys())
            # we need to filter only those functions that begin with 'test_'
            funcs = [f for f in funcs if f.startswith("test_")]
            # and also that are defined in this module (i.e. not imported from
            # other modules using the import statement, like "from sympy import
            # *"). This is tricky to achieve. The easiest is to compare m1 and
            # m2 below, if they are equal, we are sure that the "f" is from
            # module. However, when one uses the XFAIL decorator, the m1
            # appears from "sympy.utilities.pytest", so we check this one
            # explicitly. This is not robust, as it will stop working when we
            # move XFAIL to another module, or if we use some decorator defined
            # elsewhere. Any help with this is welcomed.
            funcs2 = []
            m2 = module.__name__
            for f in funcs:
                f = module.__dict__[f]
                m1 = f.__module__
                if m1 == m2 or m1 == "sympy.utilities.pytest":
                    if isgeneratorfunction(f):
                        # some tests can be generators, that return the actual
                        # test functions. We unpack it below:
                        for fg in f():
                            func = fg[0]
                            args = fg[1:]
                            fgw = lambda: func(*args)
                            funcs2.append((fgw, inspect.getsourcelines(f)[1]))
                    else:
                        funcs2.append((f, inspect.getsourcelines(f)[1]))
            funcs2.sort(key=lambda x: x[1])
            funcs = [x[0] for x in funcs2]

        # 'func' now contains all functions to test.
        self._reporter.entering_filename(filename, len(funcs))
        for f in funcs:
            self._reporter.entering_test(f)
            try:
                f()
            except KeyboardInterrupt:
                raise
            except:
                t, v, tr = sys.exc_info()
                if t is AssertionError:
                    self._reporter.test_fail((t, v, tr))
                elif t.__name__ == "Skipped":
                    self._reporter.test_skip()
                elif t.__name__ == "XFail":
                    self._reporter.test_xfail()
                elif t.__name__ == "XPass":
                    self._reporter.test_xpass()
                else:
                    self._reporter.test_exception((t, v, tr))
            else:
                self._reporter.test_pass()
        self._reporter.leaving_filename()

    def get_sympy_dir(self):
        """
        Returns the root sympy directory.
        """
        this_file = os.path.abspath(__file__)
        sympy_dir = os.path.join(os.path.dirname(this_file), "..", "..")
        sympy_dir = os.path.normpath(sympy_dir)
        return sympy_dir


    def get_paths(self, dir="", level=15):
        """
        Generates a set of paths for testfiles searching.

        Example:
        >> get_paths(2)
        ['sympy/test_*.py', 'sympy/*/test_*.py', 'sympy/*/*/test_*.py']
        >> get_paths(6)
        ['sympy/test_*.py', 'sympy/*/test_*.py', 'sympy/*/*/test_*.py',
        'sympy/*/*/*/test_*.py', 'sympy/*/*/*/*/test_*.py',
        'sympy/*/*/*/*/*/test_*.py', 'sympy/*/*/*/*/*/*/test_*.py']
        """
        wildcards = [dir]
        for i in range(level):
            wildcards.append(os.path.join(wildcards[-1], "*"))
        p = [os.path.join(x, "test_*.py") for x in wildcards]
        return p

    def get_tests(self, dir):
        """
        Returns the list of tests.
        """
        g = []
        for x in self.get_paths(dir):
            g.extend(glob(x))
        g = list(set(g))
        g.sort()
        return g

class Reporter(object):
    """
    Parent class for all reporters.
    """
    pass

class PyTestReporter(Reporter):
    """
    Py.test like reporter. Should produce output identical to py.test.
    """

    def __init__(self, verbose=False):
        self._verbose = verbose
        self._xfailed = 0
        self._xpassed = []
        self._failed = []
        self._passed = 0
        self._skipped = 0
        self._exceptions = []

    def root_dir(self, dir):
        self._root_dir = dir

    def write(self, text):
        sys.stdout.write(text)
        sys.stdout.flush()

    def write_center(self, text, delim="="):
        width = 80
        if text != "":
            text = " %s " % text
        idx = (width-len(text)) / 2
        t = delim*idx + text + delim*(width-idx-len(text))
        self.write(t+"\n")

    def write_exception(self, e, val, tb):
        t = traceback.extract_tb(tb)
        # remove the first item, as that is always runtests.py
        t = t[1:]
        t = traceback.format_list(t)
        self.write("".join(t))
        t = traceback.format_exception_only(e, val)
        self.write("".join(t))

    def start(self):
        self.write_center("test process starts")
        self.write("py.test like reporting.\n\n")
        self._t_start = clock()

    def finish(self):
        self._t_end = clock()
        self.write("\n")
        text = "tests finished: %d passed" % self._passed
        if len(self._failed) > 0:
            text += ", %d failed" % len(self._failed)
        if self._skipped > 0:
            text += ", %d skipped" % self._skipped
        if self._xfailed > 0:
            text += ", %d xfailed" % self._xfailed
        if len(self._xpassed) > 0:
            text += ", %d xpassed" % len(self._xpassed)
        if len(self._exceptions) > 0:
            text += ", %d exceptions" % len(self._exceptions)
        text += " in %.2f seconds" % (self._t_end - self._t_start)


        if len(self._xpassed) > 0:
            self.write_center("xpassed tests", "_")
            for e in self._xpassed:
                self.write("%s:%s\n" % (e[0], e[1].__name__))
            self.write("\n")

        if len(self._exceptions) > 0:
            #self.write_center("These tests raised an exception", "_")
            for e in self._exceptions:
                filename, f, (t, val, tb) = e
                self.write_center("", "_")
                if f is None:
                    s = "%s" % filename
                else:
                    s = "%s:%s" % (filename, f.__name__)
                self.write_center(s, "_")
                self.write_exception(t, val, tb)
            self.write("\n")

        if len(self._failed) > 0:
            #self.write_center("Failed", "_")
            for e in self._failed:
                filename, f, (t, val, tb) = e
                self.write_center("", "_")
                self.write_center("%s:%s" % (filename, f.__name__), "_")
                self.write_exception(t, val, tb)
            self.write("\n")

        self.write_center(text)
        ok = len(self._failed) == 0 and len(self._exceptions) == 0
        if not ok:
            self.write("DO *NOT* COMMIT!\n")
        return ok

    def entering_filename(self, filename, n):
        rel_name = filename[len(self._root_dir)+1:]
        self._active_file = rel_name
        self.write(rel_name)
        self.write("[%d] " % n)

    def leaving_filename(self):
        self.write("\n")
        if self._verbose:
            self.write("\n")

    def entering_test(self, f):
        self._active_f = f
        if self._verbose:
            self.write("\n"+f.__name__+" ")

    def test_xfail(self):
        self._xfailed += 1
        self.write("f")

    def test_xpass(self):
        self._xpassed.append((self._active_file, self._active_f))
        self.write("X")

    def test_fail(self, exc_info):
        self._failed.append((self._active_file, self._active_f, exc_info))
        self.write("F")

    def test_pass(self):
        self._passed += 1
        if self._verbose:
            self.write("ok")
        else:
            self.write(".")

    def test_skip(self):
        self._skipped += 1
        self.write("s")

    def test_exception(self, exc_info):
        self._exceptions.append((self._active_file, self._active_f, exc_info))
        self.write("E")

    def import_error(self, filename, exc_info):
        self._exceptions.append((filename, None, exc_info))
        self.write("Failed to import: %s\n" % filename)
