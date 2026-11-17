import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import Showrunner

// The token open for editing. A custom one shows its name, its kind (Text, From a pattern, Combined), what it holds
// and, for a pattern, where it searches; under that its value on the selected file and how many files of the batch
// give one. Every token, built-in ones too, has its value map: values as read, each written as something else. A
// field is written when it is left or Enter is pressed.
Rectangle {
    id: editor

    required property var token
    readonly property bool custom: token.index >= 0

    objectName: "tokenEditor"
    implicitHeight: body.implicitHeight + 2 * Theme.space_lg
    radius: Theme.radius_lg
    color: Theme.panel_2
    border.width: Theme.stroke
    border.color: Theme.line_strong

    component Problems: Repeater {
        delegate: UiText {
            required property var modelData

            Layout.fillWidth: true
            text: modelData
            color: Theme.drop
            font.pixelSize: Theme.text_xs
            wrapMode: Text.WordWrap
        }
    }

    component Label: UiText {
        Layout.fillWidth: true
        color: Theme.muted
        font.pixelSize: Theme.text_sm
        font.weight: Font.Medium
    }

    ColumnLayout {
        id: body

        anchors.fill: parent
        anchors.margins: Theme.space_lg
        spacing: Theme.space_md

        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.space_md

            UiText {
                text: editor.custom ? editor.token.name : editor.token.label
                font.weight: Font.DemiBold
            }

            UiText {
                Layout.fillWidth: true
                text: editor.custom ? Strings.t("tokens.editor.title") : Strings.t("tokens.editor.builtin")
                color: Theme.faint
                font.pixelSize: Theme.text_xs
            }

            IconButton {
                implicitWidth: Theme.row_sm
                implicitHeight: Theme.row_sm
                iconName: "x"
                label: Strings.t("tokens.editor.close")
                onClicked: editor.custom ? app.edit_token(-1) : app.edit_builtin("")
            }
        }

        Label {
            visible: editor.custom
            text: Strings.t("tokens.editor.name")
        }

        InputField {
            objectName: "tokenName"
            visible: editor.custom
            Layout.fillWidth: true
            mono: true
            label: Strings.t("tokens.editor.name")
            text: editor.token.name
            onEditingFinished: if (text !== editor.token.name) app.rename_token(editor.token.index, text)
        }

        Problems {
            model: editor.token.name_problems || []
        }

        Row {
            Layout.fillWidth: true
            visible: editor.custom
            spacing: Theme.space_xs

            Repeater {
                model: ["constant", "pattern", "composite"]

                delegate: ActionButton {
                    required property var modelData

                    kind: checked ? "outline" : "ghost"
                    size: Theme.row_sm
                    checkable: true
                    checked: editor.token.kind === modelData
                    text: Strings.t("tokens.editor.kind." + modelData)
                    onClicked: app.set_token_kind(editor.token.index, modelData)
                }
            }
        }

        Label {
            visible: editor.token.kind === "pattern"
            text: Strings.t("tokens.editor.searched")
        }

        Flow {
            Layout.fillWidth: true
            visible: editor.token.kind === "pattern"
            spacing: Theme.space_xs

            Repeater {
                model: ["file-name", "folder-1", "folder-2", "folder-3"]

                delegate: ActionButton {
                    required property var modelData

                    kind: checked ? "outline" : "ghost"
                    size: Theme.row_sm
                    checkable: true
                    checked: editor.token.source === modelData
                    text: Strings.t("tokens.editor.source." + modelData)
                    onClicked: app.set_token_source(editor.token.index, modelData)
                }
            }
        }

        Label {
            visible: editor.custom
            text: editor.token.text_label || ""
            wrapMode: Text.WordWrap
            elide: Text.ElideNone
        }

        InputField {
            objectName: "tokenText"
            visible: editor.custom
            Layout.fillWidth: true
            mono: true
            label: editor.token.text_label
            text: editor.token.text
            onEditingFinished: if (text !== editor.token.text) app.set_token_text(editor.token.index, text)
        }

        Problems {
            model: editor.token.text_problems || []
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.space_md

            UiText {
                Layout.fillWidth: true
                text: editor.token.value_label
                color: Theme.faint
                font.pixelSize: Theme.text_sm
            }

            UiText {
                mono: true
                text: editor.token.value !== "" ? editor.token.value : Strings.t("tokens.editor.nothing")
                color: editor.token.value !== "" ? Theme.control : Theme.faint
                font.weight: Font.Medium
            }

            UiText {
                visible: editor.custom
                text: editor.token.found || ""
                color: Theme.faint
                font.pixelSize: Theme.text_sm
            }
        }

        RowLayout {
            Layout.fillWidth: true
            Layout.topMargin: Theme.space_sm
            spacing: Theme.space_md

            Label {
                text: Strings.t("tokens.maps.title")
            }

            HelpTip {
                objectName: "replaceValuesTip"
                topic: "replace_values"
            }
        }

        UiText {
            Layout.fillWidth: true
            text: editor.token.raw !== "" ? editor.token.raw : Strings.t("tokens.maps.hint")
            color: Theme.faint
            font.pixelSize: Theme.text_xs
            wrapMode: Text.WordWrap
            elide: Text.ElideNone
        }

        // One row per rewrite, then an empty row that adds one. Clearing what a row reads removes it.
        Repeater {
            model: editor.token.maps

            delegate: RowLayout {
                id: mapRow

                required property var modelData
                required property int index

                Layout.fillWidth: true
                spacing: Theme.space_sm

                InputField {
                    objectName: "mapRead_" + mapRow.index
                    Layout.fillWidth: true
                    Layout.preferredWidth: 1
                    mono: true
                    label: Strings.t("tokens.maps.read")
                    placeholderText: Strings.t("tokens.maps.read")
                    text: mapRow.modelData.read
                    onEditingFinished: if (text !== mapRow.modelData.read)
                        app.set_value_map(editor.token.name, mapRow.index, text, written.text)
                }

                Icon {
                    name: "arrow"
                    size: Theme.icon_sm
                    color: Theme.faint
                }

                InputField {
                    id: written

                    objectName: "mapWritten_" + mapRow.index
                    Layout.fillWidth: true
                    Layout.preferredWidth: 1
                    mono: true
                    label: Strings.t("tokens.maps.written")
                    placeholderText: Strings.t("tokens.maps.written")
                    text: mapRow.modelData.written
                    onEditingFinished: if (text !== mapRow.modelData.written && mapRow.modelData.read !== "")
                        app.set_value_map(editor.token.name, mapRow.index, mapRow.modelData.read, text)
                }
            }
        }

        ActionButton {
            visible: editor.custom
            kind: "ghost"
            size: Theme.row_sm
            iconName: "x"
            text: Strings.t("tokens.editor.delete")
            onClicked: app.remove_token(editor.token.index)
        }
    }
}
