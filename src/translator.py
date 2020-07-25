from __future__ import annotations

import syntax
from syntax import Scope, Binder, Expr, Bool, Int, UnaryExpr, BinaryExpr, NaryExpr
from syntax import AppExpr, QuantifierExpr, Id, Let, IfThenElse, ModifiesClause
from syntax import DefinitionDecl, RelationDecl, FunctionDecl, ConstantDecl, StateDecl
from syntax import Program, SortDecl

from typing import Any, Callable, cast, Dict, Iterable, Iterator, List, Optional, Tuple
from typing import Union

import itertools
import z3
import z3_utils
from networkx import DiGraph  # type: ignore

z3_UNOPS: Dict[str, Optional[Callable[[z3.ExprRef], z3.ExprRef]]] = {
    'NOT': z3.Not,
    'NEW': None
}

z3_BINOPS: Dict[str, Callable[[z3.ExprRef, z3.ExprRef], z3.ExprRef]] = {
    'IMPLIES': z3.Implies,
    'IFF': lambda x, y: x == y,
    'EQUAL': lambda x, y: x == y,
    'NOTEQ': lambda x, y: x != y,
    'GE': lambda x, y: x >= y,
    'GT': lambda x, y: x > y,
    'LE': lambda x, y: x <= y,
    'LT': lambda x, y: x < y,
    'PLUS': lambda x, y: x + y,
    'SUB': lambda x, y: x - y,
}

z3_NOPS: Any = {
    'AND': z3.And,
    'OR': z3.Or,
    'DISTINCT': z3.Distinct,
}


class Z3Translator(object):
    def __init__(self, scope: Scope[z3.ExprRef], keys: Tuple[str, ...] = ()) -> None:
        self.scope = scope
        self.keys = keys
        self.counter = 0

    def bind(self, binder: Binder) -> List[z3.ExprRef]:
        bs = []
        for sv in binder.vs:
            # in the presence of shadowing, we need to make sure every call to z3.Const is for a unique name
            n = sv.name + '_%s' % (self.counter,)
            self.counter += 1
            assert sv.sort is not None and not isinstance(sv.sort, syntax.SortInferencePlaceholder)
            bs.append(z3.Const(n, Z3Translator.sort_to_z3(sv.sort)))
        return bs

    def get_key_opt(self, index: int) -> Optional[str]:
        if index < len(self.keys):
            return self.keys[index]
        else:
            return None

    def translate_expr(self, expr: Expr, index: int = 0) -> z3.ExprRef:
        if isinstance(expr, Bool):
            return z3.BoolVal(expr.val)
        elif isinstance(expr, Int):
            return z3.IntVal(expr.val)
        elif isinstance(expr, UnaryExpr):
            if expr.op == 'NEW':
                assert index + 1 < len(self.keys)
                return self.translate_expr(expr.arg, index=index + 1)
            else:
                unop = z3_UNOPS[expr.op]
                assert unop is not None
                return unop(self.translate_expr(expr.arg, index))
        elif isinstance(expr, BinaryExpr):
            binop = z3_BINOPS[expr.op]
            return binop(self.translate_expr(expr.arg1, index), self.translate_expr(expr.arg2, index))
        elif isinstance(expr, NaryExpr):
            nop = z3_NOPS[expr.op]
            return nop([self.translate_expr(arg, index) for arg in expr.args])
        elif isinstance(expr, AppExpr):
            d = self.scope.get(expr.callee)
            assert d is not None
            if isinstance(d, DefinitionDecl):
                # checked by resolver; see NOTE(calling-stateful-definitions)
                assert index + d.num_states <= len(self.keys)
                # now translate args in the scope of caller
                translated_args = [self.translate_expr(arg, index) for arg in expr.args]
                with self.scope.fresh_stack():
                    with self.scope.in_scope(d.binder, translated_args):
                        return self.translate_expr(d.expr, index)  # translate body of def in fresh scope
            else:
                assert isinstance(d, RelationDecl) or isinstance(d, FunctionDecl)
                k = self.get_key_opt(index)
                assert not d.mutable or k is not None
                callee = Z3Translator.statedecl_to_z3(d, k)
                assert isinstance(callee, z3.FuncDeclRef)
                app_translated_args = [self.translate_expr(arg, index) for arg in expr.args]
                translated_app = callee(*app_translated_args)
                return translated_app
        elif isinstance(expr, QuantifierExpr):
            bs = self.bind(expr.binder)
            with self.scope.in_scope(expr.binder, bs):
                e = self.translate_expr(expr.body, index)
            q = z3.ForAll if expr.quant == 'FORALL' else z3.Exists
            return q(bs, e)
        elif isinstance(expr, Id):
            d = self.scope.get(expr.name)
            assert d is not None, expr.name
            if isinstance(d, RelationDecl) or \
               isinstance(d, ConstantDecl):
                k = self.get_key_opt(index)
                assert not d.mutable or k is not None
                z3sym = Z3Translator.statedecl_to_z3(d, k)
                assert isinstance(z3sym, z3.ExprRef)
                e = z3sym
                return e
            elif isinstance(d, DefinitionDecl):
                # checked in resolver; see NOTE(calling-stateful-definitions)
                assert index + d.num_states <= len(self.keys)
                with self.scope.fresh_stack():
                    return self.translate_expr(d.expr, index)
            else:
                assert not isinstance(d, FunctionDecl)  # impossible since functions have arity > 0
                e, = d
                return e
        elif isinstance(expr, IfThenElse):
            return z3.If(self.translate_expr(expr.branch, index),
                         self.translate_expr(expr.then, index),
                         self.translate_expr(expr.els, index))
        elif isinstance(expr, Let):
            val = self.translate_expr(expr.val, index)
            with self.scope.in_scope(expr.binder, [val]):
                return self.translate_expr(expr.body, index)
        else:
            assert False, expr

    def frame(self, mods: Iterable[ModifiesClause], index: int = 0) -> List[z3.ExprRef]:
        frame = []
        R: Iterator[StateDecl] = iter(self.scope.relations.values())
        C: Iterator[StateDecl] = iter(self.scope.constants.values())
        F: Iterator[StateDecl] = iter(self.scope.functions.values())
        for d in itertools.chain(R, C, F):
            if not d.mutable or (isinstance(d, RelationDecl) and d.is_derived()) or \
               any(mc.name == d.name for mc in mods):
                continue

            k_new = self.get_key_opt(index + 1)
            k_old = self.get_key_opt(index)
            assert k_new is not None
            assert k_old is not None

            if isinstance(d, ConstantDecl) or len(d.arity) == 0:
                lhs = Z3Translator.statedecl_to_z3(d, k_new)
                rhs = Z3Translator.statedecl_to_z3(d, k_old)
                assert isinstance(lhs, z3.ExprRef) and isinstance(rhs, z3.ExprRef)
                e = lhs == rhs
            else:
                cs: List[z3.ExprRef] = []
                i = 0
                for s in d.arity:
                    cs.append(z3.Const('x' + str(i), Z3Translator.sort_to_z3(s)))
                    i += 1

                lhs = Z3Translator.statedecl_to_z3(d, k_new)
                rhs = Z3Translator.statedecl_to_z3(d, k_old)
                assert isinstance(lhs, z3.FuncDeclRef) and isinstance(rhs, z3.FuncDeclRef)

                e = z3.Forall(cs, lhs(*cs) == rhs(*cs))

            frame.append(e)

        return frame

    def translate_transition_body(self, t: DefinitionDecl, index: int = 0) -> z3.ExprRef:
        return z3.And(self.translate_expr(t.expr, index=index),
                      *self.frame(t.mods, index=index))

    def translate_transition(self, t: DefinitionDecl, index: int = 0) -> z3.ExprRef:
        bs = self.bind(t.binder)
        with self.scope.in_scope(t.binder, bs):
            body = self.translate_transition_body(t, index=index)
            if bs:
                return z3.Exists(bs, body)
            else:
                return body

    @staticmethod
    def sort_to_z3(s: Union[syntax.Sort, syntax.SortDecl]) -> z3.SortRef:
        if isinstance(s, syntax.UninterpretedSort):
            assert s.decl is not None, str(s)
            s = s.decl

        if isinstance(s, syntax.SortDecl):
            if s.z3 is None:
                s.z3 = z3.DeclareSort(s.name)
            return s.z3
        elif isinstance(s, syntax._BoolSort):
            return z3.BoolSort()
        elif isinstance(s, syntax._IntSort):
            return z3.IntSort()
        else:
            assert False

    @staticmethod
    def function_to_z3(f: syntax.FunctionDecl, key: Optional[str]) -> z3.FuncDeclRef:
        if f.mutable:
            assert key is not None
            if key not in f.mut_z3:
                a = [Z3Translator.sort_to_z3(s) for s in f.arity] + [Z3Translator.sort_to_z3(f.sort)]
                f.mut_z3[key] = z3.Function(key + '_' + f.name, *a)

            return f.mut_z3[key]
        else:
            if f.immut_z3 is None:
                a = [Z3Translator.sort_to_z3(s) for s in f.arity] + [Z3Translator.sort_to_z3(f.sort)]
                f.immut_z3 = z3.Function(f.name, *a)

            return f.immut_z3

    @staticmethod
    def relation_to_z3(r: syntax.RelationDecl, key: Optional[str]) -> Union[z3.FuncDeclRef, z3.ExprRef]:
        if r.mutable:
            assert key is not None
            if key not in r.mut_z3:
                if r.arity:
                    a = [Z3Translator.sort_to_z3(s) for s in r.arity] + [z3.BoolSort()]
                    r.mut_z3[key] = z3.Function(key + '_' + r.name, *a)
                else:
                    r.mut_z3[key] = z3.Const(key + '_' + r.name, z3.BoolSort())

            return r.mut_z3[key]
        else:
            if r.immut_z3 is None:
                if r.arity:
                    a = [Z3Translator.sort_to_z3(s) for s in r.arity] + [z3.BoolSort()]
                    r.immut_z3 = z3.Function(r.name, *a)
                else:
                    r.immut_z3 = z3.Const(r.name, z3.BoolSort())

            return r.immut_z3

    @staticmethod
    def constant_to_z3(c: syntax.ConstantDecl, key: Optional[str]) -> z3.ExprRef:
        if c.mutable:
            assert key is not None
            if key not in c.mut_z3:
                c.mut_z3[key] = z3.Const(key + '_' + c.name, Z3Translator.sort_to_z3(c.sort))

            return c.mut_z3[key]
        else:
            if c.immut_z3 is None:
                c.immut_z3 = z3.Const(c.name, Z3Translator.sort_to_z3(c.sort))

            return c.immut_z3

    @staticmethod
    def statedecl_to_z3(d: syntax.StateDecl, key: Optional[str]) -> Union[z3.FuncDeclRef, z3.ExprRef]:
        if isinstance(d, syntax.RelationDecl):
            return Z3Translator.relation_to_z3(d, key)
        elif isinstance(d, syntax.ConstantDecl):
            return Z3Translator.constant_to_z3(d, key)
        else:
            assert isinstance(d, syntax.FunctionDecl)
            return Z3Translator.function_to_z3(d, key)


def sort_from_z3sort(prog: Program, z3sort: z3.SortRef) -> SortDecl:
    return prog.scope.get_sort_checked(str(z3sort))

def qa_edges_expr(prog: Program, expr: Expr) -> Iterator[Tuple[str, str]]:
    lator = Z3Translator(cast(Scope[z3.ExprRef], prog.scope))
    z3expr = lator.translate_expr(expr)
    for (ssortz3, tsortz3) in z3_utils.z3_quantifier_alternations(z3expr):
        yield (sort_from_z3sort(prog, ssortz3).name,
               sort_from_z3sort(prog, tsortz3).name)  # TODO: consider overriding equals instead of using the names


def quantifier_alternation_graph(prog: Program, exprs: List[Expr]) -> DiGraph:
    qa_graph = DiGraph()

    for expr in exprs:
        qa_graph.add_edges_from(qa_edges_expr(prog, expr))

    return qa_graph

def decls_quantifier_alternation_graph(prog: Program, additional: List[Expr]) -> DiGraph:
    res = quantifier_alternation_graph(prog,
                                       [axiom.expr for axiom in prog.axioms()] +
                                       [cast(Expr, rel.derived_axiom) for rel in prog.derived_relations()] +
                                       additional)
    for f in prog.functions():
        for asort in f.arity:
            esort = f.sort
            res.add_edge(prog.scope.get_sort_checked(str(asort)).name,
                         prog.scope.get_sort_checked(str(esort)).name)

    return res
