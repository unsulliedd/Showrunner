import QtQuick
import QtQuick.Controls.Basic
import Showrunner

// A tooltip in the theme's colors that wraps long text. The default one is a single unstyled line, as wide as its
// text. Declared inside the item it explains; it opens under it unless `x` and `y` say otherwise.
ToolTip {
    id: tip

    x: 0
    y: parent ? parent.height + Theme.space_xs : 0
    padding: Theme.space_md
    implicitWidth: Math.min(Theme.tip_width, contentItem.implicitWidth + leftPadding + rightPadding)

    contentItem: UiText {
        width: tip.availableWidth
        text: tip.text
        wrapMode: Text.WordWrap
        elide: Text.ElideNone
        lineHeight: 1.25
        ToolTip.visible: false
    }

    background: Rectangle {
        radius: Theme.radius_md
        color: Theme.panel_2
        border.width: Theme.stroke
        border.color: Theme.line_strong
    }
}
