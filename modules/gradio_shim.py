"""
Gradio compatibility shim.

Registers itself as 'gradio' in sys.modules so that any
`import gradio as gr` resolves here instead of the real package.

Provides a minimal gr.update() and stub classes so legacy handler
functions in chat.py, extensions.py, etc. remain callable.
"""

import sys
import types


def update(**kwargs):
    """Return a plain dict in place of gr.update()."""
    result = {'__type__': 'update'}
    result.update(kwargs)
    return result


class _Stub:
    """Catch-all attribute stub for any gr.* usage."""
    def __init__(self, *args, **kwargs):
        pass

    def __call__(self, *args, **kwargs):
        return self

    def __getattr__(self, name):
        return _Stub()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def __iter__(self):
        return iter([])


# Common Gradio component stubs
Column = _Stub
Row = _Stub
Tab = _Stub
Blocks = _Stub
Button = _Stub
Textbox = _Stub
Dropdown = _Stub
Slider = _Stub
Checkbox = _Stub
CheckboxGroup = _Stub
State = _Stub
Audio = _Stub
File = _Stub
Image = _Stub
HTML = _Stub
Markdown = _Stub
Number = _Stub
Radio = _Stub
Accordion = _Stub
Group = _Stub
Dataset = _Stub
Gallery = _Stub
HighlightedText = _Stub
Label = _Stub
Plot = _Stub
Video = _Stub
MultimodalTextbox = _Stub
ColorPicker = _Stub
UploadButton = _Stub
ClearButton = _Stub
LoginButton = _Stub
LogoutButton = _Stub
Dataframe = _Stub
JSON = _Stub


class _ThemeStub:
    def __init__(self, *args, **kwargs):
        pass
    def set(self, **kwargs):
        return self


class themes:
    Default = _ThemeStub
    Soft = _ThemeStub
    Glass = _ThemeStub
    Monochrome = _ThemeStub
    Base = _ThemeStub


class _WarningStub:
    """Accept warning filter calls."""
    @staticmethod
    def filterwarnings(*args, **kwargs):
        pass


warnings = _WarningStub


def install_shim():
    """Register this module as 'gradio' in sys.modules."""
    current_module = sys.modules[__name__]

    # Create a fake 'gradio' module
    gradio_module = types.ModuleType('gradio')
    gradio_module.__package__ = 'gradio'
    gradio_module.__path__ = []

    # Copy all public attributes
    for attr in dir(current_module):
        if not attr.startswith('_') and attr != 'install_shim':
            setattr(gradio_module, attr, getattr(current_module, attr))

    sys.modules['gradio'] = gradio_module

    # Also stub common submodules
    for submod in ['gradio.themes', 'gradio.utils', 'gradio.components',
                   'gradio.blocks', 'gradio.routes', 'gradio.helpers']:
        stub = types.ModuleType(submod)
        stub.__package__ = 'gradio'
        stub.__path__ = []
        # Give it update and _Stub for any attribute access
        stub.update = update
        stub.__getattr__ = lambda self, name: _Stub()
        sys.modules[submod] = stub


# Auto-install on import if gradio isn't already available
if 'gradio' not in sys.modules:
    try:
        import gradio  # Check if real gradio exists
    except ImportError:
        install_shim()
