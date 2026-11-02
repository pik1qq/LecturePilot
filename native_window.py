"""Two-button Windows taskbar controller; GUI imports are lazy for offline tests."""
TITLE='Lecture Pilot by pik1'

def run(resources, status, open_panel, shutdown, finished, focus_requested, background=False, theme=lambda:'light'):
    import tkinter as tk
    from tkinter import ttk,messagebox
    import ctypes
    from pathlib import Path
    try:ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('pik1.LecturePilot')
    except (AttributeError,OSError):pass
    root=tk.Tk();root.title(TITLE);root.geometry('500x440');root.minsize(480,420)
    try:root.iconbitmap(str(Path(resources)/'app-icon.ico'))
    except tk.TclError:pass
    try:
        image=tk.PhotoImage(file=str(Path(resources)/'app-icon.png'));root.iconphoto(True,image)
    except tk.TclError:image=None
    style=ttk.Style(root);style.theme_use('clam')
    def apply_theme(value):
        dark=value=='dark';bg='#202020' if dark else '#F7F6F3';fg='#F3F2EF' if dark else '#252724';sub='#B7B5AF' if dark else '#666A63';button='#383838' if dark else '#FFFFFF';border='#595959' if dark else '#D2D4CE'
        root.configure(bg=bg)
        try:
            suffix='-dark' if dark else ''
            root.iconbitmap(str(Path(resources)/('app-icon'+suffix+'.ico')))
            current_image[0]=tk.PhotoImage(file=str(Path(resources)/('app-icon'+suffix+'.png')))
            root.iconphoto(True,current_image[0])
        except tk.TclError:pass
        style.configure('Pilot.TFrame',background=bg)
        style.configure('Pilot.TLabel',background=bg,foreground=fg,font=('Segoe UI',11))
        style.configure('Title.TLabel',background=bg,foreground=fg,font=('Segoe UI',20,'bold'))
        style.configure('Sub.TLabel',background=bg,foreground=sub,font=('Segoe UI',11))
        for key in ('Pilot.TButton','Quit.TButton'):
            style.configure(key,background=button,foreground=fg,bordercolor=border,lightcolor=border,darkcolor=border,font=('Segoe UI',11,'bold' if key=='Quit.TButton' else 'normal'),padding=(14,12))
            style.map(key,background=[('active','#494949' if dark else '#EAECE8')],foreground=[('disabled',sub)])
        try:
            flag=ctypes.c_int(1 if dark else 0)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(root.winfo_id(),20,ctypes.byref(flag),ctypes.sizeof(flag))
        except (AttributeError,OSError,TypeError,ValueError):pass
    current_image=[image]
    current_theme=[None]
    def sync_theme():
        value=theme()
        if value not in ('light','dark'):value='light'
        if value!=current_theme[0]:apply_theme(value);current_theme[0]=value
    sync_theme()
    frame=ttk.Frame(root,padding=24,style='Pilot.TFrame');frame.pack(fill='both',expand=True)
    ttk.Label(frame,text='Lecture Pilot',style='Title.TLabel').pack(anchor='w')
    ttk.Label(frame,text='by pik1',style='Sub.TLabel').pack(anchor='w',pady=(2,16))
    live=tk.StringVar(value='Загружаем состояние…')
    ttk.Label(frame,textvariable=live,wraplength=420,style='Pilot.TLabel').pack(anchor='w',fill='x',pady=(0,16))
    opening=ttk.Button(frame,text='Открыть панель',style='Pilot.TButton',command=open_panel);opening.pack(fill='x',pady=(0,8))
    closing=[False]
    def close_all():
        if closing[0]:return
        if not messagebox.askyesno(TITLE,'Завершить приложение и закрыть его панель и окно лекции? Обычные вкладки не затрагиваются.',parent=root):return
        closing[0]=True
        live.set('Завершаем приложение и закрываем его окна…')
        opening.state(['disabled']);quit_button.state(['disabled']);shutdown()
    quit_button=ttk.Button(frame,text='Завершить всё',style='Quit.TButton',command=close_all);quit_button.pack(fill='x',pady=(0,16))
    ttk.Label(frame,text='Сворачивание и закрытие страницы не останавливают программу. Крестик этого окна — завершить всё.',wraplength=420,style='Sub.TLabel').pack(anchor='w',fill='x')
    root.protocol('WM_DELETE_WINDOW',close_all)
    def tick():
        if finished():root.destroy();return
        sync_theme()
        if focus_requested():root.deiconify();root.lift();root.focus_force()
        if not closing[0]:live.set(status())
        root.after(250,tick)
    root.after(250,tick)
    if background:root.after(100,root.iconify)
    root.mainloop()
