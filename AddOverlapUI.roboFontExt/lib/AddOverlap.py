from AppKit import NSApp, NSColor, NSTextAlignmentRight, NSTextAlignmentLeft
from vanilla import EditText, TextBox, Window
from AppKit import NSImage
from fontTools.ufoLib.pointPen import AbstractPointPen
from lib.UI.toolbarGlyphTools import ToolbarGlyphTools
from mojo.events import addObserver
from mojo.extensions import setExtensionDefault, getExtensionDefault, registerExtensionDefaults, removeExtensionDefault
from mojo.UI import CurrentGlyphWindow
from mojo.UI import CurrentWindow
import math
import os
import re

# updated AbstractPointPen to fontTools
# added UI for the offset value
windowViewManger = {}

def getLength(pt1, pt2):
    x1, y1 = pt1
    x2, y2 = pt2
    return math.sqrt((x2-x1)**2 + (y2-y1)**2)

def pointOnACurve(curve, value):
    (x1, y1), (cx1, cy1), (cx2, cy2), (x2, y2) = curve
    dx = x1
    cx = (cx1 - dx) * 3.0
    bx = (cx2 - cx1) * 3.0 - cx
    ax = x2 - dx - cx - bx

    dy = y1
    cy = (cy1 - dy) * 3.0
    by = (cy2 - cy1) * 3.0 - cy
    ay = y2 - dy - cy - by

    mx = ax*(value)**3 + bx*(value)**2 + cx*(value) + dx
    my = ay*(value)**3 + by*(value)**2 + cy*(value) + dy

    return mx, my

class AddOverlapPointPen(AbstractPointPen):

    def __init__(self, selectedPoints=[], offset=30):
        self.offset = int(offset)
        self.selectedPoints = selectedPoints

        self._contours = []
        self._components = []

    def beginPath(self):
        self._contours.append([])
        self.firstSegment = None
        self.prevOncurve = None

    def addPoint(self, pt, segmentType=None, smooth=False, name=None, **kwargs):
        data = dict(point=pt, segmentType=segmentType, smooth=smooth, name=name, kwargs=kwargs)
        self._contours[-1].append(data)

    def endPath(self):
        pass

    def addComponent(self, baseGlyphName, transformation):
        pass

    def _offset(self, pt1, pt2):
        x1, y1 = pt1
        x2, y2 = pt2
        length = getLength((x1, y1), (x2, y2))
        if length == 0:
            return 0, 0
        ox = (x2-x1)/length*self.offset
        oy = (y2-y1)/length*self.offset
        return int(round(ox)), int(round(oy))

    def drawPoints(self, outpen):
        for pointsData in self._contours:
            if len(pointsData) == 1:
                # ignore single movetos and anchors
                continue
            outpen.beginPath()
            lenPointsData = len(pointsData)
            for i, pointData in enumerate(pointsData):
                currentPoint = pointData["point"]
                addExtraPoint = None
                if pointData["segmentType"] and pointData["point"] in self.selectedPoints:
                    prevPointData = pointsData[i-1]
                    nextPointData = pointsData[(i+1) % lenPointsData]

                    prevOffsetX, prevOffsetY = self._offset(prevPointData["point"], pointData["point"])
                    nextOffsetX, nextOffsetY = self._offset(pointData["point"], nextPointData["point"])

                    if (nextOffsetX, nextOffsetY) == (0, 0) and nextPointData["segmentType"] is None:
                        nextSegment = [
                            pointsData[(i+3) % lenPointsData]["point"],
                            pointsData[(i+2) % lenPointsData]["point"],
                            nextPointData["point"],
                            pointData["point"]
                            ]
                        newPoint = pointOnACurve(nextSegment, 0.9)
                        nextOffsetX, nextOffsetY = self._offset(pointData["point"], newPoint)
                    addExtraPoint = currentPoint[0] - nextOffsetX, currentPoint[1] - nextOffsetY

                    if (prevOffsetX, prevOffsetY) == (0, 0) and prevPointData["segmentType"] is None:
                        prevSegment = [
                            pointsData[i-3]["point"],
                            pointsData[i-2]["point"],
                            prevPointData["point"],
                            pointData["point"]
                            ]
                        newPoint = pointOnACurve(prevSegment, 0.9)
                        prevOffsetX, prevOffsetY = self._offset(newPoint, pointData["point"])
                    currentPoint = currentPoint[0] + prevOffsetX, currentPoint[1] + prevOffsetY

                outpen.addPoint(currentPoint,
                    pointData["segmentType"],
                    pointData["smooth"],
                    pointData["name"],
                    **pointData["kwargs"]
                    )

                if addExtraPoint:
                    outpen.addPoint(addExtraPoint, "line")

            outpen.endPath()

        for baseGlyphName, transformation in self._components:
            outpen.addComponent(baseGlyphName, transformation)


class AddOverlapTool(object):

    base_path = os.path.dirname(__file__)
    toolValue = 0

    def __init__(self):

        self.prefKey = 'com.okaytype.addOverlap'
        initialDefaults = {
            self.pref:   '-30',
            }
        registerExtensionDefaults(initialDefaults)
        self.toolValue = getExtensionDefault(self.pref)

        addObserver(self, "addOverlapToolbarItem", "glyphWindowWillShowToolbarItems")
        addObserver(self, "addOverlapValueUI", "glyphWindowWillOpen")
        addObserver(self, 'updateSelfWindow', 'currentGlyphChanged')


    @property
    def pref(self):
        return self.prefKey + '.' + 'addOverlapValue'

    def prefSave(self, sender):
        setExtensionDefault(self.prefKey+'.addOverlapValue', self.w.t.get())
        v = getExtensionDefault(self.pref)
        print('set', v)

    def prefGet(self, sender):
        v = getExtensionDefault(self.pref)
        print('get', v)


    def addOverlapToolbarItem(self, info):

        toolbarItems = info['toolbarItems']

        label = 'Add Overlap w/ UI'
        identifier = 'addOverlapUI'
        filename = 'AddOverlapButtonUI.pdf'
        callback = self.addOverlap
        index = -2

        imagePath = os.path.join(self.base_path, 'resources', filename)
        image = NSImage.alloc().initByReferencingFile_(imagePath)

        view = ToolbarGlyphTools((30, 25),
            [dict(image=image, toolTip=label)], trackingMode="one")

        newItem = dict(itemIdentifier=identifier,
            label = label,
            callback = callback,
            view = view
        )

        toolbarItems.insert(index, newItem)

    @property
    def wwwindow(self):
        return CurrentGlyphWindow()
    @property
    def bar(self):
        if not self.wwwindow:
            return
        return self.wwwindow.getGlyphStatusBar()

    def addOverlapValueUI(self, window):
        if not self.bar:
            return
        if hasattr(self.bar, "interpolationStatusLabel"):
            del self.bar.interpolationStatusLabel
        if hasattr(self.bar, "interpolationStatusMenu"):
            del self.bar.interpolationStatusMenu

        xywh = (-17, 0, 14, 16)
        self.bar.interpolationStatusLabel = TextBox(xywh, '⋉')
        self.bar.interpolationStatusLabel.getNSTextField().setAlignment_(NSTextAlignmentLeft)

        xywh = (-56, 4, 40, 12)
        self.bar.interpolationStatusMenu = EditText(xywh, self.toolValue, sizeStyle='mini', continuous=True, callback=self.editTextCallback)
        self.bar.interpolationStatusMenu.getNSTextField().setBezeled_(False)
        self.bar.interpolationStatusMenu.getNSTextField().setBackgroundColor_(NSColor.clearColor())
        self.bar.interpolationStatusMenu.getNSTextField().setAlignment_(NSTextAlignmentRight)

    def editTextCallback(self, sender):
        self.toolValue = self.onlynumbers(sender.get())
        if len(self.toolValue) > 0 and self.toolValue[-1] != '-':
            sender.set(self.toolValue)
            setExtensionDefault(self.prefKey+'.addOverlapValue', self.toolValue)

    def onlynumbers(self, v):
        v = v.replace(' ', '')
        if v == None or v == '': 
            v = '0'
        if v == '-0': 
            v = '0'
        negpos = ''
        if v[0] and v[0] == '-' and v != '0':
            negpos = '-'
        v = negpos + re.sub(r'[-\D]', '', v)
        return v

    def updateSelfWindow(self, notification):
        self.window = CurrentWindow()




    def addOverlap(self, sender):

        offset = self.toolValue
        if self.toolValue == '':
            offset = 0

        g = CurrentGlyph()

        selection = []

        for p in g.selectedPoints:
            p.selected = False
            selection.append((p.x, p.y))

        pen = AddOverlapPointPen(selection, offset)

        g.drawPoints(pen)

        g.prepareUndo("addOverlap")
        g.clearContours()

        pen.drawPoints(g.getPointPen())

        g.performUndo()
        g.changed()

AddOverlapTool()