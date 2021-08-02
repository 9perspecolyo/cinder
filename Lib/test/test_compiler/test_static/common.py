import ast
import asyncio
import gc
import inspect
import sys
from compiler.static import StaticCodeGenerator
from compiler.static.symbol_table import SymbolTable
from compiler.static.types import TypedSyntaxError
from contextlib import contextmanager

import cinder
from cinder import StrictModule
from test.support import maybe_get_event_loop_policy

from ..common import CompilerTest

try:
    import cinderjit
except ImportError:
    cinderjit = None


class StaticTestBase(CompilerTest):
    def compile(
        self,
        code,
        generator=StaticCodeGenerator,
        modname="<module>",
        optimize=0,
        peephole_enabled=True,
        ast_optimizer_enabled=True,
    ):
        if (
            not peephole_enabled
            or not ast_optimizer_enabled
            or generator is not StaticCodeGenerator
        ):
            return super().compile(
                code,
                generator,
                modname,
                optimize,
                peephole_enabled,
                ast_optimizer_enabled,
            )

        symtable = SymbolTable(StaticCodeGenerator)
        code = inspect.cleandoc("\n" + code)
        tree = ast.parse(code)
        return symtable.compile(modname, f"{modname}.py", tree, optimize)

    def type_error(self, code, pattern):
        with self.assertRaisesRegex(TypedSyntaxError, pattern):
            self.compile(code)

    _temp_mod_num = 0

    def _temp_mod_name(self):
        StaticTestBase._temp_mod_num += 1
        return sys._getframe().f_back.f_back.f_back.f_back.f_code.co_name + str(
            StaticTestBase._temp_mod_num
        )

    def _finalize_module(self, name, mod_dict=None):
        if name in sys.modules:
            del sys.modules[name]
        if mod_dict is not None:
            mod_dict.clear()
        gc.collect()

    def _in_module(self, code, name, code_gen, optimize):
        compiled = self.compile(code, code_gen, name, optimize)
        m = type(sys)(name)
        d = m.__dict__
        sys.modules[name] = m
        exec(compiled, d)
        d["__name__"] = name
        return d

    @contextmanager
    def in_module(self, code, name=None, code_gen=StaticCodeGenerator, optimize=0):
        d = None
        if name is None:
            name = self._temp_mod_name()
        try:
            d = self._in_module(code, name, code_gen, optimize)
            yield d
        finally:
            self._finalize_module(name, d)

    def _in_strict_module(
        self,
        code,
        name,
        code_gen,
        optimize,
        enable_patching,
    ):
        compiled = self.compile(code, code_gen, name, optimize)
        d = {"__name__": name}
        m = StrictModule(d, enable_patching)
        sys.modules[name] = m
        exec(compiled, d)
        return d, m

    @contextmanager
    def in_strict_module(
        self,
        code,
        name=None,
        code_gen=StaticCodeGenerator,
        optimize=0,
        enable_patching=False,
    ):
        d = None
        if name is None:
            name = self._temp_mod_name()
        try:
            d, m = self._in_strict_module(
                code, name, code_gen, optimize, enable_patching
            )
            yield m
        finally:
            self._finalize_module(name, d)

    def _run_code(self, code, generator, modname, peephole_enabled):
        if modname is None:
            modname = self._temp_mod_name()
        return modname, super().run_code(code, generator, modname, peephole_enabled)

    def run_code(self, code, generator=None, modname=None, peephole_enabled=True):
        _, r = self._run_code(code, generator, modname, peephole_enabled)
        return r

    @property
    def base_size(self):
        class C:
            __slots__ = ()

        return sys.getsizeof(C())

    @property
    def ptr_size(self):
        return 8 if sys.maxsize > 2 ** 32 else 4

    def assert_jitted(self, func):
        if cinderjit is None:
            return

        self.assertTrue(cinderjit.is_jit_compiled(func), func.__name__)

    def assert_not_jitted(self, func):
        if cinderjit is None:
            return

        self.assertFalse(cinderjit.is_jit_compiled(func))

    def assert_not_jitted(self, func):
        if cinderjit is None:
            return

        self.assertFalse(cinderjit.is_jit_compiled(func))

    def setUp(self):
        # ensure clean classloader/vtable slate for all tests
        cinder.clear_classloader_caches()
        # ensure our async tests don't change the event loop policy
        policy = maybe_get_event_loop_policy()
        self.addCleanup(lambda: asyncio.set_event_loop_policy(policy))

    def subTest(self, **kwargs):
        cinder.clear_classloader_caches()
        return super().subTest(**kwargs)

    def make_async_func_hot(self, func):
        async def make_hot():
            for i in range(50):
                await func()

        asyncio.run(make_hot())