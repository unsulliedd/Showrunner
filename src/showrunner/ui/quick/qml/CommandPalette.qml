import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import Showrunner

// The command palette under the top bar's search field: files, the batch's tracks, tokens and actions that match
// what is typed (the actions alone while nothing is). The field keeps the keyboard: Up and Down move through the
// results, Return runs one, Escape leaves. Python ranks the results; this only draws them.
Popup {
    id: finder

    required property Item field
    property int current: 0
    readonly property var results: app.palette

    objectName: "palette"
    x: field.x + (field.width - width) / 2
    y: field.y + field.height + Theme.space_sm
    width: Theme.palette_width
    padding: Theme.space_sm
    // The field keeps focus while the palette shows.
    focus: false
    closePolicy: Popup.CloseOnPressOutsideParent
    onResultsChanged: current = 0

    function move(by) {
        if (results.length > 0)
            current = (current + by + results.length) % results.length
        list.positionViewAtIndex(current, ListView.Contain)
    }

    function run(index) {
        const result = results[index]
        if (result === undefined)
            return
        close()
        field.focus = false
        app.palette_run(result.kind, result.key)
    }

    background: Rectangle {
        radius: Theme.radius_md
        color: Theme.panel_2
        border.width: Theme.stroke
        border.color: Theme.line_strong
    }

    contentItem: ColumnLayout {
        spacing: 0

        ListView {
            id: list

            objectName: "paletteResults"
            Layout.fillWidth: true
            Layout.preferredHeight: Math.min(contentHeight, Theme.row_md * 10)
            model: finder.results
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            ScrollBar.vertical: Scroller {}
            Accessible.role: Accessible.List
            Accessible.name: Strings.t("palette.results")

            delegate: AbstractButton {
                id: result

                required property var modelData
                required property int index
                readonly property bool isCurrent: index === finder.current

                width: ListView.view.width
                implicitHeight: Theme.row_md
                hoverEnabled: true
                focusPolicy: Qt.NoFocus
                Accessible.role: Accessible.ListItem
                Accessible.name: modelData.label
                Accessible.selected: isCurrent
                onHoveredChanged: if (hovered) finder.current = index
                onClicked: finder.run(index)

                background: Rectangle {
                    radius: Theme.radius_sm
                    color: result.isCurrent ? Theme.select : "transparent"

                    // The select fill alone is faint on the palette's panel, so the current row is also marked.
                    Rectangle {
                        visible: result.isCurrent
                        width: Theme.underline
                        height: parent.height - 2 * Theme.space_sm
                        anchors.verticalCenter: parent.verticalCenter
                        radius: width / 2
                        color: Theme.control
                    }
                }

                contentItem: RowLayout {
                    spacing: Theme.space_md

                    Icon {
                        Layout.leftMargin: Theme.space_md
                        name: ({"file": "film", "track": "audio", "token": "brace", "action": "arrow"})[result.modelData.kind]
                        size: Theme.icon_sm
                        color: result.isCurrent ? Theme.control : Theme.faint
                    }

                    UiText {
                        Layout.fillWidth: true
                        text: result.modelData.label
                    }

                    UiText {
                        Layout.maximumWidth: finder.width / 3
                        mono: result.modelData.kind === "file" || result.modelData.kind === "token"
                        text: result.modelData.detail
                        color: Theme.faint
                        font.pixelSize: Theme.text_xs
                    }

                    UiText {
                        Layout.rightMargin: Theme.space_md
                        text: Strings.t("palette.kind." + result.modelData.kind)
                        color: Theme.faint
                        font.pixelSize: Theme.text_xs
                    }
                }
            }
        }

        UiText {
            Layout.fillWidth: true
            Layout.margins: Theme.space_md
            visible: finder.results.length === 0
            text: Strings.t("palette.none")
            color: Theme.muted
            wrapMode: Text.WordWrap
            elide: Text.ElideNone
        }
    }
}
