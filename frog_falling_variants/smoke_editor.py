"""Off-screen integration check of Tk editor and its render/save worker."""
import tkinter as tk
from tkinter import ttk
from editor import main

loop=tk.Tk.mainloop
def smoke(app,*args,**kwargs):
    app.withdraw()
    attempts=[0]; started=[False]; succeeded=[False]
    def descendants(w):
        for child in w.winfo_children():
            yield child
            yield from descendants(child)
    def check():
        attempts[0]+=1
        widgets=list(descendants(app))
        canvases=[w for w in widgets if isinstance(w,tk.Canvas)]
        labels=[w for w in widgets if isinstance(w,ttk.Label)]
        if not started[0]:
            assert len(canvases)==3 and all(c.find_all() for c in canvases)
            # Select B and Pose C through real widget commands.
            combo=next(w for w in widgets if isinstance(w,ttk.Combobox))
            combo.set('B'); combo.event_generate('<<ComboboxSelected>>')
            next(w for w in widgets if isinstance(w,ttk.Radiobutton) and w.cget('text')=='Pose C').invoke()
            next(w for w in widgets if isinstance(w,ttk.Button) and '重新產生' in str(w.cget('text'))).invoke()
            started[0]=True
        elif any('已更新六個姿勢' in str(w.cget('text')) for w in labels):
            succeeded[0]=True; app.destroy(); return
        if attempts[0]>120: app.destroy(); return
        app.after(500,check)
    app.after(300,check); loop(app,*args,**kwargs)
    assert succeeded[0], 'Editor failed to regenerate and save selected variant'
    print('PASS: Tk source rig and two previews populated; B/Pose C selected; six-pose worker regenerated and saved successfully.')

if __name__=='__main__':
    tk.Tk.mainloop=smoke
    main()
