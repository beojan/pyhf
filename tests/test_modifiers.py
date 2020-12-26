import pytest
import inspect

import pyhf

modifiers_to_test = [
    "histosys",
    "normfactor",
    "normsys",
    "shapefactor",
    "shapesys",
    "staterror",
]
modifier_pdf_types = ["normal", None, "normal", None, "poisson", "normal"]


# we make sure modifiers have right structure
def test_modifiers_structure():
    from pyhf.modifiers import modifier

    @modifier(name='myUnconstrainedModifier')
    class myCustomModifier:
        @classmethod
        def required_parset(cls, sample_data, modifier_data):
            pass

    assert inspect.isclass(myCustomModifier)
    assert 'myUnconstrainedModifier' in pyhf.modifiers.registry
    assert pyhf.modifiers.registry['myUnconstrainedModifier'] == myCustomModifier
    assert pyhf.modifiers.registry['myUnconstrainedModifier'].is_constrained is False
    del pyhf.modifiers.registry['myUnconstrainedModifier']

    @modifier(name='myConstrainedModifier', constrained=True)
    class myCustomModifier:
        @classmethod
        def required_parset(cls, sample_data, modifier_data):
            pass

    assert inspect.isclass(myCustomModifier)
    assert 'myConstrainedModifier' in pyhf.modifiers.registry
    assert pyhf.modifiers.registry['myConstrainedModifier'] == myCustomModifier
    assert pyhf.modifiers.registry['myConstrainedModifier'].is_constrained is True
    del pyhf.modifiers.registry['myConstrainedModifier']


# we make sure decorate can use auto-naming
def test_modifier_name_auto():
    from pyhf.modifiers import modifier

    @modifier
    class myCustomModifier:
        @classmethod
        def required_parset(cls, sample_data, modifier_data):
            pass

    assert inspect.isclass(myCustomModifier)
    assert 'myCustomModifier' in pyhf.modifiers.registry
    assert pyhf.modifiers.registry['myCustomModifier'] == myCustomModifier
    del pyhf.modifiers.registry['myCustomModifier']


# we make sure decorate can use auto-naming with keyword arguments
def test_modifier_name_auto_withkwargs():
    from pyhf.modifiers import modifier

    @modifier(name=None, constrained=False)
    class myCustomModifier:
        @classmethod
        def required_parset(cls, sample_data, modifier_data):
            pass

    assert inspect.isclass(myCustomModifier)
    assert 'myCustomModifier' in pyhf.modifiers.registry
    assert pyhf.modifiers.registry['myCustomModifier'] == myCustomModifier
    del pyhf.modifiers.registry['myCustomModifier']


# we make sure decorate allows for custom naming
def test_modifier_name_custom():
    from pyhf.modifiers import modifier

    @modifier(name='myCustomName')
    class myCustomModifier:
        @classmethod
        def required_parset(cls, sample_data, modifier_data):
            pass

    assert inspect.isclass(myCustomModifier)
    assert 'myCustomModifier' not in pyhf.modifiers.registry
    assert 'myCustomName' in pyhf.modifiers.registry
    assert pyhf.modifiers.registry['myCustomName'] == myCustomModifier
    del pyhf.modifiers.registry['myCustomName']


# we make sure decorate raises errors if passed more than one argument, or not a string
def test_decorate_with_wrong_values():
    from pyhf.modifiers import modifier

    with pytest.raises(ValueError):

        @modifier('too', 'many', 'args')
        class myCustomModifier:
            pass

    with pytest.raises(TypeError):

        @modifier(name=1.5)
        class myCustomModifierTypeError:
            pass

    with pytest.raises(ValueError):

        @modifier(unused='arg')
        class myCustomModifierValueError:
            pass
