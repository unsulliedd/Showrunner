import QtQuick
import QtQuick.Layouts
import Showrunner

// The label over a setting, with an optional note at its right ("used when originals are kept").
RowLayout {
    id: label

    property string text
    property string note: ""

    Layout.fillWidth: true
    Layout.topMargin: Theme.space_md
    spacing: Theme.space_md

    UiText {
        Layout.fillWidth: true
        text: label.text
        font.weight: Font.DemiBold
    }

    UiText {
        visible: label.note !== ""
        text: label.note
        color: Theme.faint
        font.pixelSize: Theme.text_sm
    }
}
