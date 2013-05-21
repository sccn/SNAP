import direct.gui.OnscreenImage
from pandac.PandaModules import *
from framework.eventmarkers.eventmarkers import send_marker

def create_worldspace_gizmo(
        position=(0,0,0),               # where to create the gizmo
        hpr=(0,0,0),                    # heading/pitch/roll
        image='icons/downarrow.png',    # image to use for the gizmo
        color=(1,1,1,0.75),             # color tinting of the image
        scale=2,                        # scale of the object
        throughwalls=True,              # whether the gizmo shines through whalls
        camera_mask=(),                 # list of camera bits from which to hide the instance
        parent=None,                    # parent scene node (e.g., render)
        engine=None,                    # engine to use to create the gizmo
        billboard=True,                 # whether to enable an automatic billboard effect (turn toward camera)
        tag=0):                         # stimulus tag, if any
    """Utility to create a gizmo billboard that visually indicates a world-space location."""
    send_marker("create_worldspace_gizmo(image=%s)" % image)
    gizmo = direct.gui.OnscreenImage.OnscreenImage(image = image, pos=tuple(position), hpr=hpr, scale=0, color=color, parent=parent)
    for c in camera_mask:
        gizmo.hide(BitMask32.bit(c))
    gizmo.setTransparency(TransparencyAttrib.MAlpha)
    gizmo.setScale(scale)
    if billboard:
        gizmo.setBillboardPointEye()
    if throughwalls:
        gizmo.setBin("fixed", 40)
        gizmo.setDepthTest(False)
        gizmo.setDepthWrite(False)
    gizmo.setTwoSided(True)
    send_marker('Stimulus/Visual/3d Object, Experiment Control/Synchronization/Tag/%s' % tag)
    print "Created gizmo: ", gizmo
    return gizmo

def destroy_worldspace_gizmo(gizmo,tag=0):
    print "Destroying gizmo:", gizmo
    gizmo.destroy()
    send_marker('Experiment Control/Synchronization/Tag/%s' % tag)


def create_worldspace_instance(model=None,position=(0,0,0),color=(1,1,1,0.75),scale=1.0,hpr=(0,0,0),parent=None,name='WorldspaceInstance',tag=0):
    """Utility to create a worldspace instance with a particular location, scale and color."""
    send_marker("create_worldspace_instance(name=%s)" % name)
    inst = parent.attachNewNode(name)
    inst.setPos(position[0],position[1],position[2])
    inst.setHpr(hpr[0],hpr[1],hpr[2])
    inst.setColor(color)
    model.instanceTo(inst)
    send_marker('Stimulus/Visual/3d Object, Experiment Control/Synchronization/Tag/%s' % tag)
    print "Created instance:", inst
    return inst

def destroy_worldspace_instance(inst,tag=0):
    print "Destroying instance:", inst
    inst.removeNode()
    send_marker('Experiment Control/Synchronization/Tag/%s' % tag)

def flash_objects(objects,                          # tuple or list of objects to flash
                  flash_color = (1,1,1,1),          # color while flashing
                  normal_color = (0.8,0.8,0.8,1),   # color when back to normal
                  duration=0.3,                     # duration of the flash
                  property_name = 'frameColor',     # name of the color property to change
                  tag=0,
                  ):
    """ Flash (i.e., highlight) a set of objects simultaneously for a certain duration. """
    def apply(objects,value,property_name,task=None):
        for o in objects:
            o[property_name] = value
    apply(objects,flash_color,property_name)
    send_marker('Stimulus/Visual, Experiment Control/Synchronization/Tag/%s' % tag)
    taskMgr.doMethodLater(duration,apply,'RestoreFlashedObjects',extraArgs=[objects,normal_color,property_name],appendTask=True)
