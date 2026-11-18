import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import Showrunner

// The language picker: a searchable list of every language, an optional region and, under More, a script; the tag
// shows as it is built, and a tag can be typed instead, with a check of it as it is typed. `app.language_picker` holds
// all of it; this only draws its state and sends the clicks. Escape or Cancel leaves the language as it was.
Popup {
    id: popup

    readonly property var picker: app.language_picker
    readonly property var current: picker.state
    property bool more: false

    anchors.centerIn: Overlay.overlay
    width: Theme.language_dialog_width
    padding: Theme.space_xl
    modal: true
    focus: true
    closePolicy: Popup.CloseOnEscape
    onAboutToShow: more = current.script !== ""
    onOpened: {
        languages.focusField()
    }

    Overlay.modal: Rectangle {
        color: Theme.ground
        opacity: 0.6  // a proportion: the window stays readable behind the dialog
    }

    background: Rectangle {
        radius: Theme.radius_lg
        color: Theme.panel_2
        border.width: Theme.stroke
        border.color: Theme.line_strong
    }

    Connections {
        target: popup.picker

        function onOpened() {
            popup.open()
        }
    }

    contentItem: ColumnLayout {
        spacing: Theme.space_lg

        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.space_md

            UiText {
                Layout.fillWidth: true
                text: popup.current.title
                font.pixelSize: Theme.text_lg
                font.weight: Font.Bold
                Accessible.role: Accessible.Heading
            }

            HelpTip {
                topic: "language"
            }
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.space_lg

            EntryList {
                id: languages

                Layout.fillWidth: true
                Layout.preferredWidth: 3
                Layout.alignment: Qt.AlignTop
                listHeight: Theme.language_list_height
                fieldName: "languageSearch"
                listName: "languageList"
                label: Strings.t("language.search")
                placeholder: Strings.t("language.search")
                model: popup.picker.language_model
                selected: popup.current.language
                onFiltered: text => popup.picker.set_query(text)
                onPicked: code => popup.picker.select_language(code)
            }

            ColumnLayout {
                Layout.fillWidth: true
                Layout.preferredWidth: 2
                Layout.alignment: Qt.AlignTop
                spacing: Theme.space_md

                UiText {
                    text: Strings.t("language.region")
                    color: Theme.muted
                    font.pixelSize: Theme.text_sm
                }

                EntryList {
                    id: regions

                    Layout.fillWidth: true
                    listHeight: Theme.language_side_height
                    fieldName: "regionSearch"
                    listName: "regionList"
                    label: Strings.t("language.region")
                    placeholder: Strings.t("language.region_search")
                    model: popup.picker.region_model
                    selected: popup.current.region
                    onFiltered: text => popup.picker.set_region_query(text)
                    onPicked: code => popup.picker.select_region(code)
                }

                ActionButton {
                    objectName: "languageMore"
                    kind: "ghost"
                    text: Strings.t(popup.more ? "language.fewer" : "language.more")
                    onClicked: popup.more = !popup.more
                }

                EntryList {
                    id: scripts

                    Layout.fillWidth: true
                    visible: popup.more
                    listHeight: Theme.language_side_height
                    fieldName: "scriptSearch"
                    listName: "scriptList"
                    label: Strings.t("language.script")
                    placeholder: Strings.t("language.script_search")
                    model: popup.picker.script_model
                    selected: popup.current.script
                    onFiltered: text => popup.picker.set_script_query(text)
                    onPicked: code => popup.picker.select_script(code)
                }
            }
        }

        // The tag as it is built, and its name.
        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.space_md

            UiText {
                text: Strings.t("language.tag")
                color: Theme.muted
                font.pixelSize: Theme.text_sm
            }

            UiText {
                objectName: "languageTag"
                text: popup.current.tag !== "" ? popup.current.tag : Strings.t("language.tag_empty")
                mono: true
                color: popup.current.tag !== "" ? Theme.ink : Theme.faint
                font.weight: Font.DemiBold
                Accessible.name: Strings.t("language.tag") + " " + text
            }

            UiText {
                Layout.fillWidth: true
                text: popup.current.name
                color: Theme.muted
            }
        }

        // Or type the tag: the lists follow it, and the line beside it says whether it is one.
        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.space_md

            UiText {
                text: Strings.t("language.typed")
                color: Theme.muted
                font.pixelSize: Theme.text_sm
            }

            InputField {
                objectName: "languageTyped"
                Layout.preferredWidth: Theme.names_width / 2
                mono: true
                label: Strings.t("language.typed")
                placeholderText: Strings.t("language.typed_placeholder")
                invalid: popup.current.check.state === "error"
                text: popup.current.typed
                onTextEdited: popup.picker.set_typed(text)
                onAccepted: if (popup.current.can_apply) apply.clicked()
            }

            UiText {
                objectName: "languageCheck"
                Layout.fillWidth: true
                text: popup.current.check.text
                color: popup.current.check.state === "error" ? Theme.drop
                       : popup.current.check.state === "warn" ? Theme.change : Theme.muted
                font.pixelSize: Theme.text_sm
                wrapMode: Text.WordWrap
                elide: Text.ElideNone
            }
        }

        RowLayout {
            Layout.alignment: Qt.AlignRight
            spacing: Theme.space_md

            ActionButton {
                objectName: "languageClear"
                visible: popup.current.clearable
                kind: "ghost"
                text: Strings.t("language.clear")
                onClicked: {
                    popup.picker.clear()
                    popup.close()
                }
            }

            ActionButton {
                kind: "ghost"
                text: Strings.t("common.cancel")
                onClicked: popup.close()
            }

            ActionButton {
                id: apply

                objectName: "languageApply"
                kind: "primary"
                enabled: popup.current.can_apply
                text: Strings.t("language.apply")
                onClicked: {
                    popup.picker.apply()
                    popup.close()
                }
            }
        }
    }
}
