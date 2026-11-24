from PySide6.QtWidgets import QComboBox,QDialog,QFormLayout

class Wardrobe(QDialog):
    def __init__(self,parent,settings):
        super().__init__(parent)
        self.setWindowTitle("Avatar wardrobe")
        self.setMinimumWidth(320)
        self.selection={}
        form=QFormLayout(self)
        categories=[
            ("Eyewear","eyewear",[("None","none"),("Classic frames","classic"),("Amber aviators","aviators"),("Round wire frames","round"),("Googly goggles","googly"),("Pixel deal-with-it shades","pixel")]),
            ("Headwear","hat",[("None","none"),("Ribbed beanie","beanie"),("Baseball cap","cap"),("Propeller beanie","propeller"),("Traffic cone","cone")]),
            ("Accessories","jewelry",[("None","none"),("Gold chain","chain"),("Silver pendant","pendant"),("Spinning bow tie","bow"),("Emergency pizza slice","pizza")])]
        for label,key,items in categories:
            picker=QComboBox()
            for title,value in items:picker.addItem(title,value)
            default="classic" if key=="eyewear" and settings.value("glasses",True,bool) else "none"
            picker.setCurrentIndex(max(0,picker.findData(settings.value("wardrobe/"+key,default))))
            self.selection[key]=picker.currentData()
            def select(index,box=picker,name=key):
                self.selection[name]=box.currentData()
                settings.setValue("wardrobe/"+name,box.currentData())
            picker.currentIndexChanged.connect(select)
            form.addRow(label,picker)
