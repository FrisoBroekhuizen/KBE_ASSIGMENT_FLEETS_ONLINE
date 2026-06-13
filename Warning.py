from tkinter import Tk, messagebox


def generate_warning(warning_header: str, msg: str) -> None:
    """Generate a warning dialog box, wait for user confirmation and close it, used for variety of warnings troughout the files"""
    window = Tk()
    window.withdraw()

    messagebox.showwarning(warning_header, msg)

    window.deiconify()
    window.destroy()
    window.quit()
