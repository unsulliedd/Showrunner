import QtQuick
import QtQuick.Layouts
import Showrunner

// A short line under a setting that says what it does; `tone` colours a problem or a result.
UiText {
    property string tone: "muted"

    Layout.fillWidth: true
    visible: text !== ""
    color: tone === "drop" ? Theme.drop : tone === "add" ? Theme.add : tone === "change" ? Theme.change : Theme.muted
    font.pixelSize: Theme.text_sm
    wrapMode: Text.WordWrap
    elide: Text.ElideNone
}
