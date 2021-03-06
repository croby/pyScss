from scss.compat import ChainMap
from scss.cssdefs import _has_placeholder_re


def normalize_var(name):
    if isinstance(name, basestring):
        return name.replace('_', '-')
    else:
        return name

class Namespace(object):
    """..."""

    def __init__(self, variables=None, functions=None, mixins=None):
        if variables is None:
            self._variables = ChainMap()
        else:
            self._variables = ChainMap(variables)

        if functions is None:
            self._functions = ChainMap()
        else:
            self._functions = ChainMap(functions._functions)

        self._mixins = ChainMap()

    @classmethod
    def derive_from(cls, *others):
        self = cls()
        if len(others) == 1:
            self._variables = others[0]._variables.new_child()
            self._functions = others[0]._functions.new_child()
            self._mixins = others[0]._mixins.new_child()
        else:
            self._variables = ChainMap(other._variables for other in others)
            self._functions = ChainMap(other._functions for other in others)
            self._mixins = ChainMap(other._mixins for other in others)
        return self

    def derive(self):
        return type(self).derive_from(self)


    def variable(self, name):
        name = normalize_var(name)
        return self._variables[name]

    def set_variable(self, name, value):
        name = normalize_var(name)
        assert not (isinstance(value, basestring) and value.startswith('$'))
        #assert isinstance(value, Value)
        self._variables[name] = value

    def _get_callable(self, chainmap, name, arity):
        name = normalize_var(name)
        if arity is not None:
            # With explicit arity, try the particular arity before falling back
            # to the general case (None)
            try:
                return chainmap[name, arity]
            except KeyError:
                pass

        return chainmap[name, None]

    def _set_callable(self, chainmap, name, arity, cb):
        name = normalize_var(name)
        chainmap[name, arity] = cb

    def mixin(self, name, arity):
        return self._get_callable(self._mixins, name, arity)

    def set_mixin(self, name, arity, cb):
        self._set_callable(self._mixins, name, arity, cb)

    def function(self, name, arity):
        return self._get_callable(self._functions, name, arity)

    def set_function(self, name, arity, cb):
        self._set_callable(self._functions, name, arity, cb)


class SassRule(object):
    """At its heart, a CSS rule: combination of a selector and zero or more
    properties.  But this is Sass, so it also tracks some Sass-flavored
    metadata, like `@extend` rules and `@media` nesting.
    """

    def __init__(self, source_file, unparsed_contents=None, dependent_rules=None,
            options=None, properties=None,
            namespace=None,
            lineno=0, extends_selectors=frozenset(),
            ancestry=None):

        self.source_file = source_file
        self.lineno = lineno

        self.unparsed_contents = unparsed_contents
        self.options = options
        self.extends_selectors = extends_selectors

        if namespace is None:
            assert False
            self.namespace = Namespace()
        else:
            self.namespace = namespace

        if dependent_rules is None:
            self.dependent_rules = set()
        else:
            self.dependent_rules = dependent_rules

        if properties is None:
            self.properties = []
        else:
            self.properties = properties

        self.retval = None

        if ancestry is None:
            self.ancestry = []
        else:
            self.ancestry = ancestry

    @property
    def selectors(self):
        # TEMPORARY
        if self.ancestry and self.ancestry[-1].is_selector:
            return frozenset(self.ancestry[-1].selectors)
        else:
            return frozenset()

    @selectors.setter
    def selectors(self, value):
        for header in reversed(self.ancestry):
            if header.is_selector:
                header.selectors |= value
                return
            else:
                # TODO media
                break

        self.ancestry.append(BlockSelectorHeader(value))

    @property
    def file_and_line(self):
        """Returns the filename and line number where this rule originally
        appears, in the form "foo.scss:3".  Used for error messages.
        """
        return "%s:%d" % (self.source_file.filename, self.lineno)

    @property
    def is_empty(self):
        """Returns whether this rule is considered "empty" -- i.e., has no
        contents that should end up in the final CSS.
        """
        if self.properties:
            # Rules containing CSS properties are never empty
            return False

        if self.ancestry:
            header = self.ancestry[-1]
            if header.is_atrule and header.directive != '@media':
                # At-rules should always be preserved, UNLESS they are @media
                # blocks, which are known to be noise if they don't have any
                # contents of their own
                return False

        return True

    def copy(self):
        return type(self)(
            source_file=self.source_file,
            lineno=self.lineno,
            unparsed_contents=self.unparsed_contents,

            options=self.options,
            #properties=list(self.properties),
            properties=self.properties,
            extends_selectors=self.extends_selectors,
            #ancestry=list(self.ancestry),
            ancestry=self.ancestry,

            namespace=self.namespace.derive(),
        )


class BlockHeader(object):
    """..."""
    # TODO doc me depending on how UnparsedBlock is handled...

    is_atrule = False
    is_scope = False
    is_selector = False

    @classmethod
    def parse(cls, prop):
        # Simple pre-processing
        if prop.startswith('+'):
            # Expand '+' at the beginning of a rule as @include
            prop = '@include ' + prop[1:]
            # TODO what is this, partial sass syntax?
            try:
                if '(' not in prop or prop.index(':') < prop.index('('):
                    prop = prop.replace(':', '(', 1)
                    if '(' in prop:
                        prop += ')'
            except ValueError:
                pass
        elif prop.startswith('='):
            # Expand '=' at the beginning of a rule as @mixin
            prop = '@mixin ' + prop[1:]
        elif prop.startswith('@prototype '):
            # Remove '@prototype '
            # TODO what is @prototype??
            prop = prop[11:]

        # Minor parsing
        if prop.startswith('@'):
            if prop.lower().startswith('@else if '):
                directive = '@else if'
                argument = prop[9:]
            else:
                directive, _, argument = prop.partition(' ')
                directive = directive.lower()

            return BlockAtRuleHeader(directive, argument)
        else:
            if prop.endswith(u':') or u': ' in prop:
                # Syntax is "<scope>: [prop]" -- if the optional prop exists,
                # it becomes the first rule with no suffix
                scope, unscoped_value = prop.split(u':', 1)
                scope = scope.rstrip()
                unscoped_value = unscoped_value.lstrip()
                return BlockScopeHeader(scope, unscoped_value)
            else:
                return BlockSelectorHeader(prop)


class BlockAtRuleHeader(BlockHeader):
    is_atrule = True

    def __init__(self, directive, argument):
        self.directive = directive
        self.argument = argument

    def __repr__(self):
        return "<%s %r %r>" % (self.__class__.__name__, self.directive, self.argument)

    def render(self):
        if self.argument:
            return "%s %s" % (self.directive, self.argument)
        else:
            return self.directive


class BlockSelectorHeader(BlockHeader):
    is_selector = True

    def __init__(self, selectors):
        self.selectors = selectors

    def __repr__(self):
        return "<%s %r>" % (self.__class__.__name__, self.selectors)

    def render(self, sep=', ', super_selector=''):
        return sep.join(sorted(
            super_selector + s
            for s in self.selectors
            if not _has_placeholder_re.search(s)))


class BlockScopeHeader(BlockHeader):
    is_scope = True

    def __init__(self, scope, unscoped_value):
        self.scope = scope

        if unscoped_value:
            self.unscoped_value = unscoped_value
        else:
            self.unscoped_value = None


class UnparsedBlock(object):
    """A Sass block whose contents have not yet been parsed.

    At the top level, CSS (and Sass) documents consist of a sequence of blocks.
    A block may be a ruleset:

        selector { block; block; block... }

    Or it may be an @-rule:

        @rule arguments { block; block; block... }

    Or it may be only a single property declaration:

        property: value

    pyScss's first parsing pass breaks the document into these blocks, and each
    block becomes an instance of this class.
    """

    def __init__(self, parent_rule, lineno, prop, unparsed_contents):
        self.parent_rule = parent_rule
        self.header = BlockHeader.parse(prop)

        # Basic properties
        self.lineno = lineno
        self.prop = prop
        self.unparsed_contents = unparsed_contents

    @property
    def directive(self):
        return self.header.directive

    @property
    def argument(self):
        return self.header.argument

    ### What kind of thing is this?

    @property
    def is_atrule(self):
        return self.header.is_atrule

    @property
    def is_scope(self):
        return self.header.is_scope
