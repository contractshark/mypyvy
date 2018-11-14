import ply
import ply.lex
import ply.yacc
import syntax
from typing import Any

import sys

reserved = {
    'modifies': 'MODIFIES',
    'sort': 'SORT',
    'mutable': 'MUTABLE',
    'immutable': 'IMMUTABLE',
    'derived': 'DERIVED',
    'relation': 'RELATION',
    'constant': 'CONSTANT',
    'function': 'FUNCTION',
    'init': 'INIT',
    'transition': 'TRANSITION',
    'invariant': 'INVARIANT',
    'sketch': 'SKETCH',
    'axiom': 'AXIOM',
    'old': 'OLD',
    'forall': 'FORALL',
    'exists': 'EXISTS',
    'true': 'TRUE',
    'false': 'FALSE',
    'onestate': 'ONESTATE',
    'twostate': 'TWOSTATE',
    'theorem': 'THEOREM',
    'assume': 'ASSUME',
    'automaton': 'AUTOMATON',
    'global': 'GLOBAL',
    'safety': 'SAFETY',
    'phase': 'PHASE',
    'self': 'SELF',
}

tokens = [
    'LPAREN',
    'RPAREN',
    'LBRACKET',
    'RBRACKET',
    'LBRACE',
    'RBRACE',
    'DOT',
    'COLON',
    'COLONEQUALS',
    'SEMI',
    'BANG',
    'IFF',
    'IMPLIES',
    'PIPE',
    'EQUAL',
    'NOTEQ',
    'COMMA',
    'AMPERSAND',
    'ID'
] + list(reserved.values())


def t_ID(t: Any) -> Any:
    r'[a-zA-Z_][a-zA-Z_0-9]*'
    t.type = reserved.get(t.value, 'ID')    # Check for reserved words
    return t

t_LPAREN = r'\('
t_RPAREN = r'\)'
t_LBRACKET = r'\['
t_RBRACKET = r'\]'
t_LBRACE = r'{'
t_RBRACE = r'}'
t_DOT = r'\.'
t_COLON = r':'
t_COLONEQUALS = r':='
t_SEMI = r';'
t_BANG = r'\!'
t_IMPLIES = r'->'
t_IFF = r'<->'
t_PIPE = r'\|'
t_EQUAL = r'='
t_NOTEQ = r'\!='
t_COMMA = r','
t_AMPERSAND = r'&'
t_ignore_COMMENT = r'\#.*'

# Define a rule so we can track line numbers
def t_newline(t: ply.lex.LexToken) -> None:
    r'\n+'
    t.lexer.lineno += len(t.value)
    t.lexer.bol = t.lexpos

t_ignore  = ' \t'

def t_error(t: Any) -> None:
    pass

lexer = None
def get_lexer(forbid_rebuild: bool=False) -> ply.lex.Lexer:
    global lexer
    if not lexer:
        lexer = ply.lex.lex(debug=False, forbid_rebuild=forbid_rebuild)
    return lexer

precedence = (
    ('right', 'DOT'),
    ('nonassoc', 'IFF'),
    ('right', 'IMPLIES'),
    ('left', 'PIPE'),
    ('left', 'AMPERSAND'),
    ('nonassoc', 'EQUAL', 'NOTEQ'),
    ('right', 'BANG')
)

def p_program(p: Any) -> None:
    'program : decls'
    p[0] = syntax.Program(p[1])

def p_decls_empty(p: Any) -> None:
    'decls : empty'
    p[0] = []

def p_decls_decl(p: Any) -> None:
    'decls : decls decl'
    p[0] = p[1] + [p[2]]

def p_id(p: Any) -> None:
    'id : ID'
    p[0] = p.slice[1]

def p_decl_sort(p: Any) -> None:
    'decl : SORT id'
    p[0] = syntax.SortDecl(p.slice[1], p[2].value)

def p_decl_mut(p: Any) -> None:
    '''mut : MUTABLE
           | IMMUTABLE'''
    p[0] = p[1] == 'mutable'

def p_arity_empty(p: Any) -> None:
    'arity : empty'
    p[0] = []

def p_arity_paren_empty(p: Any) -> None:
    'arity : LPAREN RPAREN'
    p[0] = []

def p_arity_nonempty(p: Any) -> None:
    'arity : LPAREN arity_nonempty RPAREN'
    p[0] = p[2]

def p_arity_nonempty_one(p: Any) -> None:
    'arity_nonempty : sort'
    p[0] = [p[1]]

def p_arity_nonempty_more(p: Any) -> None:
    'arity_nonempty : arity_nonempty COMMA sort'
    p[0] = p[1] + [p[3]]

def p_sort(p: Any) -> None:
    'sort : id'
    p[0] = syntax.UninterpretedSort(p[1], p[1].value)

def p_decl_relation(p: Any) -> None:
    'decl : mut RELATION id arity'
    p[0] = syntax.RelationDecl(p.slice[2], p[3].value, p[4], p[1])

def p_decl_relation_derived(p: Any) -> None:
    'decl : DERIVED RELATION id arity COLON expr'
    p[0] = syntax.RelationDecl(p.slice[2], p[3].value, p[4], mutable=True, derived=p[6])

def p_decl_constant(p: Any) -> None:
    'decl : mut CONSTANT id COLON sort'
    p[0] = syntax.ConstantDecl(p.slice[2], p[3].value, p[5], p[1])

def p_decl_function(p: Any) -> None:
    'decl : mut FUNCTION id LPAREN arity_nonempty RPAREN COLON sort'
    p[0] = syntax.FunctionDecl(p.slice[2], p[3].value, p[5], p[8], p[1])

def p_decl_axiom(p: Any) -> None:
    'decl : AXIOM opt_name expr'
    p[0] = syntax.AxiomDecl(p.slice[1], p[2], p[3])

def p_decl_init(p: Any) -> None:
    'decl : INIT opt_name expr'
    p[0] = syntax.InitDecl(p.slice[1], p[2], p[3])

def p_safety_or_invariant_keyword_safety(p: Any) -> None:
    'safety_or_invariant_keyword : SAFETY'
    p[0] = (p.slice[1], True, False)

def p_safety_or_invariant_keyword_invariant(p: Any) -> None:
    'safety_or_invariant_keyword : INVARIANT'
    p[0] = (p.slice[1], False, False)

def p_safety_or_invariant_keyword_sketch_invariant(p: Any) -> None:
    'safety_or_invariant_keyword : SKETCH INVARIANT'
    p[0] = (p.slice[1], False, True)

def p_invariant_decl(p: Any) -> None:
    'invariant_decl : safety_or_invariant_keyword opt_name expr'
    tok, is_safety, is_sketch = p[1]
    p[0] = syntax.InvariantDecl(tok, p[2], p[3], is_safety, is_sketch)

def p_decl_invariant(p: Any) -> None:
    'decl : invariant_decl'
    p[0] = p[1]

def p_opt_name_none(p: Any) -> None:
    'opt_name : empty'
    pass

def p_opt_name_some(p: Any) -> None:
    'opt_name : LBRACKET id RBRACKET'
    p[0] = p[2].value

def p_quant(p: Any) -> None:
    '''quant : FORALL
             | EXISTS'''
    p[0] = p.slice[1]

def p_expr_quantifier(p: Any) -> None:
    'expr : quant sortedvars DOT expr'
    p[0] = syntax.QuantifierExpr(p[1], p[1].type, p[2], p[4])

def p_sortedvar(p: Any) -> None:
    'sortedvar : id COLON sort'
    p[0] = syntax.SortedVar(p[1], p[1].value, p[3])

def p_sortedvar_nosort(p: Any) -> None:
    'sortedvar : id'
    p[0] = syntax.SortedVar(p[1], p[1].value, None)

def p_sortedvars0_one(p: Any) -> None:
    'sortedvars0 : sortedvars'
    p[0] = p[1]

def p_sortedvars0_zero(p: Any) -> None:
    'sortedvars0 : empty'
    p[0] = []

def p_sortedvars_one(p: Any) -> None:
    'sortedvars : sortedvar'
    p[0] = [p[1]]

def p_sortedvars_more(p: Any) -> None:
    'sortedvars : sortedvars COMMA sortedvar'
    p[0] = p[1] + [p[3]]

def p_expr_true(p: Any) -> None:
    'expr : TRUE'
    p[0] = syntax.Bool(p.slice[1], True)

def p_expr_false(p: Any) -> None:
    'expr : FALSE'
    p[0] = syntax.Bool(p.slice[1], False)

def p_expr_not(p: Any) -> None:
    'expr : BANG expr'
    p[0] = syntax.UnaryExpr(p.slice[1], 'NOT', p[2])

def p_expr_app(p: Any) -> None:
    'expr : id LPAREN args RPAREN'
    p[0] = syntax.AppExpr(p[1], p[1].value, p[3])

def p_expr_and(p: Any) -> None:
    'expr : expr AMPERSAND expr'
    l = p[1]
    if isinstance(l, syntax.NaryExpr) and l.op == 'AND':
        l.args.append(p[3])
        p[0] = l
    else:
        p[0] = syntax.NaryExpr(p.slice[2], 'AND', [l, p[3]])

def p_expr_or(p: Any) -> None:
    'expr : expr PIPE expr'
    l = p[1]
    if isinstance(l, syntax.NaryExpr) and l.op == 'OR':
        l.args.append(p[3])
        p[0] = l
    else:
        p[0] = syntax.NaryExpr(p.slice[2], 'OR', [l, p[3]])

def p_expr_iff(p: Any) -> None:
    'expr : expr IFF expr'
    p[0] = syntax.BinaryExpr(p.slice[2], 'IFF', p[1], p[3])
    
def p_expr_implies(p: Any) -> None:
    'expr : expr IMPLIES expr'
    p[0] = syntax.BinaryExpr(p.slice[2], 'IMPLIES', p[1], p[3])

def p_expr_eq(p: Any) -> None:
    'expr : expr EQUAL expr'
    p[0] = syntax.BinaryExpr(p.slice[2], 'EQUAL', p[1], p[3])

def p_expr_noteq(p: Any) -> None:
    'expr : expr NOTEQ expr'
    p[0] = syntax.BinaryExpr(p.slice[2], 'NOTEQ', p[1], p[3])


def p_expr_old(p: Any) -> None:
    'expr : OLD LPAREN expr RPAREN'
    p[0] = syntax.UnaryExpr(p.slice[1], 'OLD', p[3])

def p_args_empty(p: Any) -> None:
    'args : empty'
    p[0] = []

def p_args_at_least_one(p: Any) -> None:
    'args : args1'
    p[0] = p[1]

def p_args1_one(p: Any) -> None:
    'args1 : expr'
    p[0] = [p[1]]

def p_args1_more(p: Any) -> None:
    'args1 : args1 COMMA expr'
    p[0] = p[1] + [p[3]]

def p_expr_id(p: Any) -> None:
    'expr : id'
    p[0] = syntax.Id(p[1], p[1].value)

def p_expr_paren(p: Any) -> None:
    'expr : LPAREN expr RPAREN'
    p[0] = p[2]

def p_params(p: Any) -> None:
    'params : sortedvars0'
    p[0] = p[1]

def p_mod(p: Any) -> None:
    'mod : id'
    p[0] = syntax.ModifiesClause(p[1], p[1].value)

def p_modlist_one(p: Any) -> None:
    'modlist : mod'
    p[0] = [p[1]]

def p_modlist_more(p: Any) -> None:
    'modlist : modlist COMMA mod'
    p[0] = p[1] + [p[3]]

def p_mods(p: Any) -> None:
    'mods : MODIFIES modlist'
    p[0] = p[2]

def p_decl_transition(p: Any) -> None:
    'decl : TRANSITION id LPAREN params RPAREN transition_body'
    p[0] = syntax.TransitionDecl(p[2], p[2].value, p[4], p[6])

def p_decl_transition_body_mods_expr(p: Any) -> None:
    'transition_body : mods expr'
    p[0] = (p[1], p[2])

def p_decl_transition_body_block(p: Any) -> None:
    'transition_body : blockstmt'
    p[0] = p[1]

def p_blockstmt(p: Any) -> None:
    'blockstmt : LBRACE stmts RBRACE'
    p[0] = syntax.BlockStatement(p.slice[1], p[2])

def p_stmts_empty(p: Any) -> None:
    'stmts : empty'
    p[0] = []

def p_stmts_more(p: Any) -> None:
    'stmts : stmts stmt'
    p[0] = p[1] + [p[2]]

def p_stmt_assume(p: Any) -> None:
    'stmt : ASSUME expr SEMI'
    p[0] = syntax.AssumeStatement(p.slice[1], p[2])

def p_assignment_lhs_empty(p: Any) -> None:
    'assignment_lhs : empty'
    p[0] = []

def p_assignment_lhs_nonempty(p: Any) -> None:
    'assignment_lhs : LPAREN args RPAREN'
    p[0] = p[2]

def p_stmt_assignment(p: Any) -> None:
    'stmt : id assignment_lhs COLONEQUALS expr SEMI'
    p[0] = syntax.AssignmentStatement(p[1], p[1].value, p[2], p[4])

def p_onetwostate(p: Any) -> None:
    '''onetwostate : ONESTATE
                   | TWOSTATE
                   | empty'''
    p[0] = p[1] == 'twostate'

def p_decl_theorem(p: Any) -> None:
    'decl : onetwostate THEOREM opt_name expr'
    p[0] = syntax.TheoremDecl(p.slice[2], p[3], p[4], p[1])

def p_phase_target_self(p: Any) -> None:
    'phase_target : SELF'
    p[0] = None

def p_phase_target_phase(p: Any) -> None:
    'phase_target : PHASE id'
    p[0] = p[2].value

def p_phase_transition_decl(p: Any) -> None:
    'phase_component : TRANSITION id IMPLIES phase_target option_guard'
    p[0] = syntax.PhaseTransitionDecl(p.slice[1], p[2].value, p[5], p[4])

def p_option_guard_empty(p: Any) -> None:
    'option_guard : empty'
    p[0] = None

def p_option_guard_guard(p: Any) -> None:
    'option_guard : ASSUME expr'
    p[0] = p[2]

def p_phase_invariant_decl(p: Any) -> None:
    'phase_component : invariant_decl'
    p[0] = p[1]

def p_phase_components_empty(p: Any) -> None:
    'phase_components : empty'
    p[0] = []

def p_phase_components_component(p: Any) -> None:
    'phase_components : phase_components phase_component'
    p[0] = p[1] + [p[2]]

def p_adecl_global(p: Any) -> None:
    'automaton_decl : GLOBAL phase_components'
    p[0] = syntax.GlobalPhaseDecl(p.slice[1], p[2])

def p_adecl_init_phase(p: Any) -> None:
    'automaton_decl : INIT PHASE id'
    p[0] = syntax.InitPhaseDecl(p.slice[1], p[3].value)

def p_adecl_phase(p: Any) -> None:
    'automaton_decl : PHASE id phase_components'
    p[0] = syntax.PhaseDecl(p.slice[1], p[2].value, p[3])

def p_automaton_decls_empty(p: Any) -> None:
    'automaton_decls : empty'
    p[0] = []

def p_automaton_decls_decl(p: Any) -> None:
    'automaton_decls : automaton_decls automaton_decl'
    p[0] = p[1] + [p[2]]

def p_decl_automaton(p: Any) -> None:
    'decl : AUTOMATON LBRACE automaton_decls RBRACE'
    p[0] = syntax.AutomatonDecl(p.slice[1], p[3])

def p_empty(p: Any) -> None:
    'empty :'
    pass

def p_error(t: Any) -> None:
    if t is not None:
        print('error: %s: syntax error near %s' %
              ('%s:%s:%s' % (t.filename, t.lineno, t.col), t.value))
    else:
        l = get_lexer(forbid_rebuild=True)
        print('lexer is None? %s' % l is None)
        if l is None:
            raise Exception
        print('error: %s: syntax error near EOF' %
              ('%s:%s:%s' % (l.filename, l.lineno, l.lexpos - l.bol), ))

    sys.exit(1)

program_parser = None
def get_parser(forbid_rebuild: bool=False) -> ply.yacc.LRParser:
    global program_parser
    if not program_parser:
        # intentionally don's pass optimize=True here, because that disables the signature check
        program_parser = ply.yacc.yacc(start='program', debug=True)

    return program_parser


# expr_parser = ply.yacc.yacc(start='expr', errorlog=ply.yacc.NullLogger(), debug=False, optimize=True)

