import direct.gui.OnscreenImage
from pandac.PandaModules import *

def create_worldspace_gizmo(position=(0,0,0),image='icons/downarrow.png',color=(1,1,1,0.75),throughwalls=True,oncamera=False,scale=2,parent=None,engine=None):
    """Utility to create a gizmo billboard that visually indicates a world-space location."""
    gizmo = direct.gui.OnscreenImage.OnscreenImage(image = image, pos=tuple(position), scale=0, color=color, parent=parent)
    if not oncamera:
        gizmo.hide(BitMask32.bit(3))
        gizmo.hide(BitMask32.bit(4))
    gizmo.setTransparency(TransparencyAttrib.MAlpha)
    gizmo.setScale(scale)
    gizmo.setBillboardPointEye()
    if throughwalls:
        gizmo.setBin("fixed", 40)
        gizmo.setDepthTest(False)
        gizmo.setDepthWrite(False)
    gizmo.setTwoSided(True)
    return gizmo 

def destroy_worldspace_gizmo(gizmo):
    gizmo.destroy()


def create_worldspace_instance(model=None,position=(0,0,0),color=(1,1,1,0.75),scale=1.0,hpr=(0,0,0),parent=None,name='WorldspaceInstance'):
    """Utility to create a worldspace instance with a particular location, scale and color."""
    inst = parent.attachNewNode(name)
    inst.setPos(position[0],position[1],position[2])
    inst.setHpr(hpr[0],hpr[1],hpr[2])
    inst.setColor(color)
    model.instanceTo(inst)
    return inst

def destroy_worldspace_instance(inst):
    inst.removeNode()
