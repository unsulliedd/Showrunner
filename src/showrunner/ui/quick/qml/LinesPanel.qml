import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import Showrunner

// The Lines panel of the Subtitles place: the selected file's subtitle, one cue per row, with what the chosen cleanup
// does to it marked live. A dropped cue is struck, a changed one shows its new text under the old, each with the
// rule that did it. `app.lines` holds all of it; this only draws.
Item {
    id: panel

    readonly property var view: app.lines
    readonly property var rows: view.rows ?? []
    readonly property var languages: view.languages ?? []

    objectName: "linesPanel"

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Theme.space_lg
        spacing: Theme.space_md

        UiText {
            Layout.fillWidth: true
            text: panel.view.file ?? ""
            mono: true
            elide: Text.ElideMiddle
        }

        // Which of the file's subtitles, when it has several.
        Flow {
            Layout.fillWidth: true
            visible: panel.languages.length > 1
            spacing: Theme.space_sm

            Repeater {
                model: panel.languages

                delegate: ActionButton {
                    required property int index
                    required property var modelData

                    kind: modelData.current ? "outline" : "ghost"
                    size: Theme.row_sm
                    text: modelData.label
                    onClicked: app.pick_lines_file(index)
                }
            }
        }

        UiText {
            objectName: "linesSummary"
            Layout.fillWidth: true
            visible: (panel.view.summary ?? "") !== ""
            text: panel.view.summary ?? ""
            color: Theme.muted
            font.pixelSize: Theme.text_sm
            wrapMode: Text.WordWrap
        }

        UiText {
            objectName: "linesSets"
            Layout.fillWidth: true
            visible: (panel.view.sets ?? "") !== ""
            text: panel.view.sets ?? ""
            color: Theme.faint
            font.pixelSize: Theme.text_xs
            wrapMode: Text.WordWrap
        }

        UiText {
            objectName: "linesEmpty"
            Layout.fillWidth: true
            visible: (panel.view.empty ?? "") !== ""
            text: panel.view.empty ?? ""
            color: Theme.muted
            wrapMode: Text.WordWrap
        }

        ListView {
            id: list

            objectName: "linesList"
            Layout.fillWidth: true
            Layout.fillHeight: true
            visible: panel.rows.length > 0
            clip: true
            model: panel.rows
            boundsBehavior: Flickable.StopAtBounds
            ScrollBar.vertical: Scroller {}

            delegate: RowLayout {
                id: line

                required property var modelData

                width: list.width - Theme.space_lg
                spacing: Theme.space_md

                UiText {
                    Layout.preferredWidth: Theme.cue_time_width
                    Layout.alignment: Qt.AlignTop
                    text: line.modelData.time
                    color: Theme.faint
                    mono: true
                    font.pixelSize: Theme.text_xs
                }

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 0

                    UiText {
                        Layout.fillWidth: true
                        text: line.modelData.text
                        color: line.modelData.state === "dropped" ? Theme.drop : line.modelData.state === "kept" ? Theme.ink : Theme.muted
                        font.pixelSize: Theme.text_sm
                        font.strikeout: line.modelData.state === "dropped"
                        wrapMode: Text.WordWrap
                    }

                    UiText {
                        Layout.fillWidth: true
                        visible: line.modelData.after !== ""
                        text: line.modelData.after
                        color: Theme.change
                        font.pixelSize: Theme.text_sm
                        wrapMode: Text.WordWrap
                    }

                    UiText {
                        Layout.fillWidth: true
                        visible: line.modelData.rule !== ""
                        text: line.modelData.state === "looped" ? Strings.t("lines.looped") : line.modelData.rule
                        color: Theme.faint
                        font.pixelSize: Theme.text_xs
                        elide: Text.ElideRight
                    }
                }
            }
        }

        UiText {
            Layout.fillWidth: true
            visible: (panel.view.more ?? 0) > 0
            text: Strings.f("lines.more", {"count": panel.view.more ?? 0})
            color: Theme.faint
            font.pixelSize: Theme.text_xs
        }
    }
}
