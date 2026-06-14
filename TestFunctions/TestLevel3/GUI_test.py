import ast
import enum
import os
from time import sleep

from parapy.core import Attribute, Base, Input, Part, derived
from parapy.core.decorators import action
from parapy.core.widgets import (
    Button,
    CheckBox,
    ColorPicker,
    Dropdown,
    FilePicker,
    MultiCheckBox,
    ObjectPicker,
    PyField,
    SingleSelection,
    TextField,
)
from parapy.geom import Box, Cylinder

options = [True, 2.0, "bar", None]


class Color(enum.Enum):
    RED = "1"
    BLUE = "2"
    GREEN = "3"


def objectpicker_validator(value):
    return len(value) == 2, "Select 2 objects"


def generate_quote_fast(self):
    print("Generating quote fast")
    return [1, 2, 3]


def generate_quote_slow(self):
    print("Generating quote slow (2 seconds)")
    sleep(2)
    return [1, 2, 3]


class MyClass(Base):
    quote_flag1 = Input(
        widget=Button(generate_quote_fast, label="Quote Fast!")
    )

    quote_flag2 = Input(
        widget=Button(generate_quote_slow, label="Quote Slow!")
    )

    pyfield_1 = Input(None)
    pyfield_2 = Input("bar", label="My PyField")
    pyfield_3 = Input(0, widget=PyField)
    pyfield_4 = Input(0, widget=PyField(eval=ast.literal_eval))

    # statically blue
    pyfield_bg_color_1 = Input(0, widget=PyField(background_color="blue"))

    # dynamic background color
    pyfield_bg_color_2 = Input(
        0,
        widget=PyField(
            background_color=lambda self: self.pyfield_bg_color_2_background_color()
        ),
    )

    textfield_1 = Input("my text", widget=TextField)
    textfield_2 = Input("my text", widget=TextField())
    textfield_3 = Input("my text", widget=TextField(multi_line=True))

    checkbox_1 = Input(True, widget=CheckBox)
    checkbox_2 = Input(True, widget=CheckBox())
    checkbox_3 = Input(
        "Foo", widget=CheckBox(checked_value="Foo", unchecked_value="Bar")
    )
    checkbox_4 = Input(
        widget=CheckBox(checked_value="Ham", unchecked_value="Eggs")
    )

    # no autocompute
    multi_checkbox_1 = Input(
        [True, "bar"], widget=MultiCheckBox(values=options, autocompute=False)
    )
    # no autocompute, use repr instead of str
    multi_checkbox_2 = Input(
        [True, "bar"],
        widget=MultiCheckBox(values=options, str=repr, autocompute=False),
    )
    # enum
    multi_checkbox_3 = Input(
        [Color.RED, Color.GREEN],
        widget=MultiCheckBox(Color, autocompute=False),
    )
    # autocompute, with labels
    multi_checkbox_4 = Input(
        [True, "bar"],
        widget=MultiCheckBox(
            values=options, labels=["True", "2", "bar", "Nothing"]
        ),
    )
    # no autoexpand, custom separator
    multi_checkbox_5 = Input(
        [True, "bar"],
        widget=MultiCheckBox(
            values=options, separator=" | ", autoexpand=False
        ),
    )
    # all false input (i.e. empty list)
    multi_checkbox_6 = Input([], widget=MultiCheckBox(values=options))
    # missing required input
    multi_checkbox_7 = Input(widget=MultiCheckBox(values=options))

    # no autocompute
    single_selection_1 = Input(
        True, widget=SingleSelection(values=options, autocompute=False)
    )
    # no autocompute, use repr instead of str
    single_selection_2 = Input(
        2.0,
        widget=SingleSelection(values=options, str=repr, autocompute=False),
    )
    # enum
    single_selection_3 = Input(Color.RED, widget=SingleSelection(Color))
    # autocompute, with labels
    single_selection_4 = Input(
        "bar",
        widget=SingleSelection(
            values=options, labels=["True", "2", "bar", "Nothing"]
        ),
    )
    # no autoexpand (note "None" is only a valid input here because it is one
    # of the options, otherwise it would be treated as an invalid input value)
    single_selection_5 = Input(
        None, widget=SingleSelection(values=options, autoexpand=False)
    )
    # missing required input
    single_selection_6 = Input(widget=SingleSelection(values=options))

    dropdown_1 = Input(widget=Dropdown(options, autocompute=False))
    dropdown_2 = Input(
        2.0, widget=Dropdown(options, str=repr, autocompute=False)
    )
    dropdown_3 = Input(
        2.0, widget=Dropdown(options, labels=["True", "2", "bar", "Nothing"])
    )
    dropdown_4 = Input(Color.RED, widget=Dropdown(Color))

    colorpicker_1 = Input(None, widget=ColorPicker)
    colorpicker_2 = Input((192, 168, 0), widget=ColorPicker)
    colorpicker_3 = Input("red", widget=ColorPicker(system=True))

    filepicker_1 = Input(__file__, widget=FilePicker)
    # show file selection relative to current working directory
    filepicker_2 = Input(
        __file__, widget=FilePicker(relative_to_dir=os.getcwd())
    )
    # only show the filename
    filepicker_3 = Input(__file__, widget=FilePicker(full_path=False))
    # force the file dialog to always open at C:|
    filepicker_4 = Input(__file__, widget=FilePicker(default_dir="C:\\"))
    # select image dialog
    filepicker_5 = Input(
        __file__,
        widget=FilePicker(
            title="Select an image",
            wildcard="images (*.bmp,*.gif,*.jpg) |*.bmp;*.gif;*.jpg",
        ),
    )

    # select one object
    objectpicker_1 = Input(widget=ObjectPicker)
    # select multiple objects, ask confirmation
    objectpicker_2 = Input(
        widget=ObjectPicker(multiple=True, ask_confirmation=True)
    )
    # use popup dialog instead of status bar
    objectpicker_3 = Input(widget=ObjectPicker(multiple=True, popup=True))
    # validate selection (2 objects)
    objectpicker_4 = Input(
        derived,
        widget=ObjectPicker(
            msg="Select 2 objects.",
            multiple=True,
            validator=objectpicker_validator,
        ),
    )

    @objectpicker_4.getter
    def objectpicker_4(self):
        return [self.my_box]

    @Attribute
    def pyfield_error(self):
        return 1 / self.pyfield_3

    @pyfield_3.validator
    def pyfield_3(self, value):
        if value >= 5:
            return False, "Value should be smaller than 5"
        return True

    @action(icon="trash.png")
    def generate_quote_fast(self):
        print("Generating quote fast")

    @action(icon="trash.png", label="slow quote...", button_label="Now!")
    def generate_quote_slow(self):
        print("Generating quote slow (2 seconds)")
        sleep(2)

    @Part
    def my_box(self):
        return Box(3, 3, 3, centered=True, color="blue")

    @Part
    def my_cylinder(self):
        return Cylinder(1, 5, centered=True, color="orange")

    def pyfield_bg_color_2_background_color(self):
        try:
            return ["red", "green", "blue", "yellow"][self.pyfield_3]
        except IndexError:
            return "orange"


if __name__ == "__main__":
    from parapy.gui import display

    # uncomment to suppress logging errors to console and popups
    # from parapy.gui.data import DataPanel
    # DataPanel.POPUP_EXCEPTIONS = False
    # DataPanel.LOG_EXCEPTIONS = False

    obj = MyClass()
    display(obj)