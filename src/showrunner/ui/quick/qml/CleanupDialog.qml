import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import Showrunner

// The cleanup rule editor: the rule sets, the rules of the selected set, one rule's fields and, across the bottom, a
// live test of the set against sample text or the subtitle shown in the Lines panel. Built-in sets are read only. All
// state lives in `app.cleanup_editor`; this draws its view and sends every edit to a slot as it is typed.
Popup {
    id: dialog

    readonly property var editor: app.cleanup_editor
    readonly property var view: editor.view
    readonly property var current: view.set ?? ({})
    readonly property var rule: view.rule ?? ({})
    readonly property var test: view.test ?? ({})
    readonly property bool readOnly: current.readonly ?? true
    // What the name popup is for: "new" or "duplicate".
    property string naming: ""
    // A Subtitle Edit file was read: its preview, or why it could not be.
    readonly property bool importing: (view.preview ?? ({})).file !== undefined || (view.import_error ?? "") !== ""
    onImportingChanged: importing ? importPopup.open() : importPopup.close()

    objectName: "cleanupDialog"
    anchors.centerIn: Overlay.overlay
    width: Math.min(Theme.rules_dialog_width, Overlay.overlay ? Overlay.overlay.width - 2 * Theme.space_2xl : Theme.rules_dialog_width)
    height: Math.min(Theme.rules_dialog_height, Overlay.overlay ? Overlay.overlay.height - 2 * Theme.space_2xl : Theme.rules_dialog_height)
    padding: Theme.space_xl
    modal: true
    focus: true
    closePolicy: Popup.CloseOnEscape

    Overlay.modal: Rectangle {
        color: Theme.ground
        opacity: Theme.dim_percent / 100
    }

    background: Rectangle {
        radius: Theme.radius_lg
        color: Theme.panel_2
        border.width: Theme.stroke
        border.color: Theme.line_strong
    }

    Connections {
        target: dialog.editor

        function onOpened() {
            dialog.open()
        }
    }

    // A text field that follows the view except while it is being typed in, so a normalised value never moves the
    // cursor.
    component Field: InputField {
        id: field

        property string value: ""
        property string key: ""

        mono: true
        Layout.fillWidth: true
        enabled: !dialog.readOnly
        onTextEdited: dialog.editor.set_field(key, text)

        Binding {
            target: field
            property: "text"
            value: field.value
            when: !field.activeFocus
        }
    }

    component Caption: UiText {
        Layout.fillWidth: true
        Layout.topMargin: Theme.space_sm
        color: Theme.muted
        font.pixelSize: Theme.text_sm
        font.weight: Font.Medium
    }

    contentItem: ColumnLayout {
        spacing: Theme.space_lg

        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.space_md

            UiText {
                Layout.fillWidth: true
                text: Strings.t("cleanup.dialog.title")
                font.pixelSize: Theme.text_lg
                font.weight: Font.Bold
                Accessible.role: Accessible.Heading
            }

            ActionButton {
                objectName: "cleanupYaml"
                kind: "ghost"
                iconName: "terminal"
                text: Strings.t(dialog.current.yaml_shown ? "cleanup.dialog.hide_yaml" : "cleanup.dialog.show_yaml")
                visible: dialog.current.name !== undefined
                onClicked: dialog.editor.set_show_yaml(!dialog.current.yaml_shown)
            }

            ActionButton {
                kind: "ghost"
                iconName: "folder"
                text: Strings.t("cleanup.dialog.open_folder")
                onClicked: dialog.editor.open_folder()
            }

            ActionButton {
                objectName: "cleanupClose"
                text: Strings.t("cleanup.dialog.close")
                onClicked: dialog.close()
            }
        }

        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: Theme.space_lg

            // The rule sets
            ColumnLayout {
                Layout.preferredWidth: Theme.rules_set_width
                Layout.fillHeight: true
                spacing: Theme.space_md

                Caption {
                    text: Strings.t("cleanup.dialog.sets")
                }

                ListView {
                    id: setList

                    objectName: "cleanupSets"
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true
                    model: dialog.view.sets ?? []
                    spacing: Theme.space_xs
                    ScrollBar.vertical: Scroller {}

                    delegate: ItemDelegate {
                        id: setRow

                        required property var modelData

                        objectName: "cleanupSet_" + modelData.name
                        width: setList.width - Theme.space_lg
                        height: Theme.list_row
                        onClicked: dialog.editor.select_set(modelData.name)
                        Accessible.name: modelData.label

                        background: Rectangle {
                            radius: Theme.radius_md
                            color: setRow.modelData.selected ? Theme.select : setRow.hovered ? Theme.panel : "transparent"
                        }

                        contentItem: ColumnLayout {
                            spacing: 0

                            UiText {
                                Layout.fillWidth: true
                                text: setRow.modelData.label
                                font.pixelSize: Theme.text_sm
                                elide: Text.ElideRight
                            }

                            UiText {
                                Layout.fillWidth: true
                                text: setRow.modelData.languages + " · " + setRow.modelData.count
                                color: Theme.faint
                                font.pixelSize: Theme.text_xs
                                elide: Text.ElideRight
                            }
                        }
                    }
                }

                // A file that could not be read: its set is left out until it is fixed.
                Repeater {
                    model: dialog.view.problems ?? []

                    delegate: Hint {
                        required property var modelData

                        Layout.fillWidth: true
                        text: modelData.file + ": " + modelData.message
                        tone: "drop"
                        font.pixelSize: Theme.text_xs
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: Theme.space_sm

                    ActionButton {
                        objectName: "cleanupNew"
                        kind: "ghost"
                        iconName: "plus"
                        text: Strings.t("cleanup.dialog.new_set")
                        enabled: !(dialog.view.locked ?? false)
                        onClicked: {
                            dialog.naming = "new"
                            naming.open()
                        }
                    }

                    ActionButton {
                        objectName: "cleanupImport"
                        kind: "ghost"
                        iconName: "upload"
                        text: Strings.t("cleanup.dialog.import")
                        enabled: !(dialog.view.locked ?? false)
                        onClicked: dialog.editor.choose_import()
                    }
                }
            }

            // The rules of the set
            ColumnLayout {
                Layout.preferredWidth: Theme.rules_list_width
                Layout.fillHeight: true
                spacing: Theme.space_md

                Caption {
                    text: dialog.current.label ?? ""
                }

                UiText {
                    Layout.fillWidth: true
                    visible: (dialog.current.note ?? "") !== ""
                    text: dialog.current.note ?? ""
                    color: Theme.faint
                    font.pixelSize: Theme.text_xs
                    wrapMode: Text.WordWrap
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: Theme.space_sm

                    ActionButton {
                        objectName: "cleanupDuplicate"
                        kind: "ghost"
                        text: Strings.t("cleanup.dialog.duplicate")
                        visible: dialog.current.name !== undefined
                        enabled: !(dialog.view.locked ?? false)
                        onClicked: {
                            dialog.naming = "duplicate"
                            naming.open()
                        }
                    }

                    ActionButton {
                        objectName: "cleanupDelete"
                        kind: "ghost"
                        text: Strings.t("cleanup.dialog.delete")
                        visible: dialog.current.name !== undefined && !dialog.current.builtin
                        enabled: !(dialog.view.locked ?? false)
                        onClicked: confirmDelete.open()
                    }
                }

                ListView {
                    id: ruleList

                    objectName: "cleanupRules"
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true
                    model: dialog.current.rules ?? []
                    spacing: Theme.space_xs
                    ScrollBar.vertical: Scroller {}

                    delegate: Rectangle {
                        id: ruleRow

                        required property int index
                        required property var modelData

                        objectName: "cleanupRule_" + index
                        width: ruleList.width - Theme.space_lg
                        height: Theme.row_lg
                        radius: Theme.radius_md
                        color: modelData.selected ? Theme.select : ruleArea.containsMouse ? Theme.panel : "transparent"

                        MouseArea {
                            id: ruleArea

                            anchors.fill: parent
                            hoverEnabled: true
                            // The field being typed in lets go first, so what it holds is not written to the next rule.
                            onClicked: {
                                ruleList.forceActiveFocus()
                                dialog.editor.select_rule(ruleRow.index)
                            }
                        }

                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: Theme.space_sm
                            anchors.rightMargin: Theme.space_sm
                            spacing: Theme.space_sm

                            IconButton {
                                objectName: "cleanupPause_" + ruleRow.index
                                implicitWidth: Theme.row_sm
                                implicitHeight: Theme.row_sm
                                iconName: ruleRow.modelData.paused ? "play" : "pause"
                                active: ruleRow.modelData.paused
                                label: Strings.t(ruleRow.modelData.paused ? "cleanup.rule.unpause" : "cleanup.rule.pause")
                                enabled: !(dialog.view.locked ?? false)
                                onClicked: dialog.editor.toggle_pause(ruleRow.index)
                            }

                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 0

                                UiText {
                                    Layout.fillWidth: true
                                    text: ruleRow.modelData.label
                                    color: ruleRow.modelData.paused ? Theme.faint : Theme.ink
                                    font.pixelSize: Theme.text_sm
                                    font.strikeout: ruleRow.modelData.paused
                                    elide: Text.ElideRight
                                }

                                UiText {
                                    Layout.fillWidth: true
                                    text: ruleRow.modelData.kind + " · " + ruleRow.modelData.action
                                    color: Theme.faint
                                    font.pixelSize: Theme.text_xs
                                }
                            }

                            IconButton {
                                visible: !dialog.readOnly
                                implicitWidth: Theme.row_sm
                                implicitHeight: Theme.row_sm
                                iconName: "up"
                                label: Strings.t("cleanup.rule.up")
                                enabled: ruleRow.index > 0
                                onClicked: dialog.editor.move_rule(ruleRow.index, -1)
                            }

                            IconButton {
                                visible: !dialog.readOnly
                                implicitWidth: Theme.row_sm
                                implicitHeight: Theme.row_sm
                                iconName: "down"
                                label: Strings.t("cleanup.rule.down")
                                enabled: ruleRow.index < ruleList.count - 1
                                onClicked: dialog.editor.move_rule(ruleRow.index, 1)
                            }
                        }
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    visible: !dialog.readOnly && dialog.current.name !== undefined
                    spacing: Theme.space_sm

                    ActionButton {
                        objectName: "cleanupAddRule"
                        kind: "ghost"
                        iconName: "plus"
                        text: Strings.t("cleanup.rule.add")
                        onClicked: dialog.editor.add_rule()
                    }

                    ActionButton {
                        objectName: "cleanupRemoveRule"
                        kind: "ghost"
                        iconName: "x"
                        text: Strings.t("cleanup.rule.remove")
                        enabled: ruleList.count > 1
                        onClicked: dialog.editor.remove_rule((dialog.current.rules ?? []).findIndex(r => r.selected))
                    }
                }
            }

            // The rule, or the file the set is saved in
            ScrollPane {
                id: formScroll

                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true
                contentWidth: availableWidth

                ColumnLayout {
                    width: formScroll.availableWidth
                    spacing: Theme.space_sm

                    Hint {
                        objectName: "cleanupError"
                        Layout.fillWidth: true
                        visible: (dialog.current.error ?? "") !== ""
                        text: (dialog.current.error ?? "") + " " + Strings.t("cleanup.dialog.unsaved")
                        tone: "drop"
                    }

                    TextArea {
                        objectName: "cleanupYamlText"
                        Layout.fillWidth: true
                        visible: dialog.current.yaml_shown ?? false
                        readOnly: true
                        text: dialog.current.yaml ?? ""
                        color: Theme.ink
                        font.family: Theme.mono
                        font.pixelSize: Theme.text_sm
                        wrapMode: TextEdit.WrapAnywhere
                        background: Rectangle {
                            radius: Theme.radius_md
                            color: Theme.well
                        }
                    }

                    ColumnLayout {
                        Layout.fillWidth: true
                        visible: !(dialog.current.yaml_shown ?? false) && dialog.rule.name !== undefined
                        spacing: Theme.space_sm

                        Caption {
                            text: Strings.t("cleanup.field.name")
                        }

                        Field {
                            objectName: "cleanupName"
                            key: "name"
                            value: dialog.rule.name ?? ""
                            mono: false
                            label: Strings.t("cleanup.field.name")
                        }

                        Caption {
                            text: Strings.t("cleanup.field.match")
                        }

                        Segmented {
                            objectName: "cleanupKind"
                            model: [
                                {"key": "text", "label": Strings.t("cleanup.kind.text")},
                                {"key": "regex", "label": Strings.t("cleanup.kind.regex")}
                            ]
                            current: dialog.rule.kind ?? "text"
                            name: Strings.t("cleanup.field.match")
                            enabled: !dialog.readOnly
                            onPicked: key => dialog.editor.set_field("kind", key)
                        }

                        Caption {
                            text: Strings.t("cleanup.field.pattern")
                        }

                        TextArea {
                            id: pattern

                            objectName: "cleanupPattern"
                            Layout.fillWidth: true
                            Layout.preferredHeight: Theme.row_lg * 2
                            readOnly: dialog.readOnly
                            color: Theme.ink
                            font.family: Theme.mono
                            font.pixelSize: Theme.text_sm
                            wrapMode: TextEdit.WrapAnywhere
                            onTextChanged: if (activeFocus) dialog.editor.set_field("patterns", text)
                            Accessible.name: Strings.t("cleanup.field.pattern")

                            Binding {
                                target: pattern
                                property: "text"
                                value: dialog.rule.patterns ?? ""
                                when: !pattern.activeFocus
                            }

                            background: Rectangle {
                                radius: Theme.radius_md
                                color: Theme.well
                                border.width: Theme.stroke
                                border.color: (dialog.current.error ?? "") !== "" ? Theme.drop : pattern.activeFocus ? Theme.control : Theme.line
                            }
                        }

                        Caption {
                            text: Strings.t("cleanup.field.action")
                        }

                        Segmented {
                            objectName: "cleanupAction"
                            model: [
                                {"key": "replace", "label": Strings.t("cleanup.field.replace")},
                                {"key": "drop", "label": Strings.t("cleanup.field.drop")}
                            ]
                            current: dialog.rule.action ?? "replace"
                            name: Strings.t("cleanup.field.action")
                            enabled: !dialog.readOnly
                            onPicked: key => dialog.editor.set_field("action", key)
                        }

                        Field {
                            objectName: "cleanupReplacement"
                            visible: dialog.rule.action === "replace"
                            key: "replacement"
                            value: dialog.rule.replacement ?? ""
                            label: Strings.t("cleanup.field.replace_with")
                            placeholderText: Strings.t("cleanup.field.replace_hint")
                        }

                        UiText {
                            Layout.fillWidth: true
                            visible: dialog.rule.action === "drop"
                            text: Strings.t("cleanup.field.drop_hint")
                            color: Theme.faint
                            font.pixelSize: Theme.text_xs
                            wrapMode: Text.WordWrap
                        }

                        Caption {
                            text: Strings.t("cleanup.field.languages")
                        }

                        Field {
                            objectName: "cleanupLanguages"
                            key: "languages"
                            value: dialog.rule.languages ?? ""
                            label: Strings.t("cleanup.field.languages")
                            placeholderText: Strings.t("cleanup.field.languages_hint")
                        }

                        UiText {
                            Layout.fillWidth: true
                            visible: (dialog.rule.flags ?? "") !== ""
                            text: Strings.f("cleanup.field.flags", {"flags": dialog.rule.flags ?? ""})
                            color: Theme.faint
                            font.pixelSize: Theme.text_xs
                        }
                    }
                }
            }
        }

        // The test
        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: Theme.rule_test_height
            radius: Theme.radius_md
            color: Theme.panel
            border.width: Theme.stroke
            border.color: Theme.line
            visible: dialog.rule.name !== undefined

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: Theme.space_md
                spacing: Theme.space_sm

                RowLayout {
                    Layout.fillWidth: true
                    spacing: Theme.space_md

                    Segmented {
                        objectName: "cleanupSource"
                        model: [
                            {"key": "sample", "label": Strings.t("cleanup.test.sample")},
                            {"key": "subtitle", "label": Strings.t("cleanup.test.subtitle")}
                        ]
                        current: dialog.test.source ?? "sample"
                        name: Strings.t("cleanup.test.source")
                        onPicked: key => dialog.editor.set_source(key)
                    }

                    UiText {
                        objectName: "cleanupTestSummary"
                        Layout.fillWidth: true
                        text: dialog.test.summary ?? ""
                        color: Theme.muted
                        font.pixelSize: Theme.text_sm
                        elide: Text.ElideRight
                    }

                    Segmented {
                        model: [
                            {"key": "mine", "label": Strings.t("cleanup.test.only_mine")},
                            {"key": "all", "label": Strings.t("cleanup.test.every")}
                        ]
                        current: (dialog.test.only_mine ?? false) ? "mine" : "all"
                        name: Strings.t("cleanup.test.filter")
                        onPicked: key => dialog.editor.set_only_mine(key === "mine")
                    }
                }

                Hint {
                    Layout.fillWidth: true
                    visible: (dialog.test.source === "subtitle") && !(dialog.test.can_load ?? false)
                    text: Strings.t("cleanup.test.no_subtitle")
                }

                RowLayout {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    spacing: Theme.space_md

                    TextArea {
                        id: sample

                        objectName: "cleanupSample"
                        Layout.preferredWidth: Theme.rules_list_width
                        Layout.fillHeight: true
                        visible: dialog.test.source !== "subtitle"
                        color: Theme.ink
                        font.family: Theme.mono
                        font.pixelSize: Theme.text_sm
                        wrapMode: TextEdit.WrapAnywhere
                        placeholderText: Strings.t("cleanup.test.sample_hint")
                        placeholderTextColor: Theme.faint
                        onTextChanged: if (activeFocus) dialog.editor.set_sample(text)
                        Accessible.name: Strings.t("cleanup.test.sample")

                        Binding {
                            target: sample
                            property: "text"
                            value: dialog.test.sample ?? ""
                            when: !sample.activeFocus
                        }

                        background: Rectangle {
                            radius: Theme.radius_md
                            color: Theme.well
                            border.width: Theme.stroke
                            border.color: sample.activeFocus ? Theme.control : Theme.line
                        }
                    }

                    ListView {
                        id: testList

                        objectName: "cleanupTestRows"
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        clip: true
                        model: dialog.test.rows ?? []
                        ScrollBar.vertical: Scroller {}

                        delegate: RowLayout {
                            id: testRow

                            required property var modelData

                            width: testList.width - Theme.space_lg
                            spacing: Theme.space_md

                            UiText {
                                Layout.preferredWidth: Theme.cue_time_width
                                Layout.alignment: Qt.AlignTop
                                text: testRow.modelData.time
                                color: Theme.faint
                                mono: true
                                font.pixelSize: Theme.text_xs
                            }

                            UiText {
                                Layout.fillWidth: true
                                text: testRow.modelData.before
                                color: testRow.modelData.state === "dropped" ? Theme.drop : testRow.modelData.mine ? Theme.ink : Theme.muted
                                font.pixelSize: Theme.text_sm
                                font.strikeout: testRow.modelData.state === "dropped"
                                wrapMode: Text.WordWrap
                            }

                            UiText {
                                Layout.fillWidth: true
                                text: testRow.modelData.state === "looped" ? Strings.t("lines.looped") : testRow.modelData.after
                                color: Theme.change
                                font.pixelSize: Theme.text_sm
                                wrapMode: Text.WordWrap
                            }
                        }
                    }
                }
            }
        }
    }

    // A name for a new set or for a copy of the selected one.
    Popup {
        id: naming

        anchors.centerIn: Overlay.overlay
        width: Theme.dialog_width / 2
        padding: Theme.space_xl
        modal: true
        focus: true
        closePolicy: Popup.CloseOnEscape
        onOpened: {
            nameField.text = ""
            problem.text = ""
            nameField.forceActiveFocus()
        }

        background: Rectangle {
            radius: Theme.radius_lg
            color: Theme.panel_2
            border.width: Theme.stroke
            border.color: Theme.line_strong
        }

        function accept() {
            const error = dialog.naming === "new" ? dialog.editor.new_set(nameField.text) : dialog.editor.duplicate_set(nameField.text)
            problem.text = error
            if (error === "")
                close()
        }

        contentItem: ColumnLayout {
            spacing: Theme.space_md

            UiText {
                Layout.fillWidth: true
                text: Strings.t(dialog.naming === "new" ? "cleanup.dialog.new_set" : "cleanup.dialog.duplicate")
                font.weight: Font.DemiBold
            }

            InputField {
                id: nameField

                objectName: "cleanupNameField"
                Layout.fillWidth: true
                label: Strings.t("cleanup.dialog.set_name")
                placeholderText: Strings.t("cleanup.dialog.set_name")
                invalid: problem.text !== ""
                onAccepted: naming.accept()
            }

            Hint {
                id: problem

                objectName: "cleanupNameProblem"
                Layout.fillWidth: true
                visible: text !== ""
                tone: "drop"
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: Theme.space_md

                Item {
                    Layout.fillWidth: true
                }

                ActionButton {
                    text: Strings.t("common.cancel")
                    onClicked: naming.close()
                }

                ActionButton {
                    objectName: "cleanupNameOk"
                    kind: "primary"
                    text: Strings.t("cleanup.dialog.make")
                    onClicked: naming.accept()
                }
            }
        }
    }

    ConfirmPopup {
        id: confirmDelete

        heading: Strings.t("cleanup.dialog.delete")
        text: Strings.f("cleanup.dialog.delete_question", {"name": dialog.current.label ?? ""})
        yes: Strings.t("cleanup.dialog.delete")
        danger: true
        onAccepted: dialog.editor.delete_set()
    }

    // What a Subtitle Edit file would make, before anything is written.
    Popup {
        id: importPopup

        readonly property var data: dialog.view.preview ?? ({})

        objectName: "cleanupImportPreview"
        anchors.centerIn: Overlay.overlay
        width: Theme.dialog_width
        height: Math.min(Theme.dialog_width, Overlay.overlay ? Overlay.overlay.height - 2 * Theme.space_2xl : Theme.dialog_width)
        padding: Theme.space_xl
        modal: true
        focus: true
        closePolicy: Popup.CloseOnEscape
        onClosed: dialog.editor.cancel_import()

        background: Rectangle {
            radius: Theme.radius_lg
            color: Theme.panel_2
            border.width: Theme.stroke
            border.color: Theme.line_strong
        }

        contentItem: ColumnLayout {
            spacing: Theme.space_md

            UiText {
                Layout.fillWidth: true
                text: Strings.t("cleanup.import.title")
                font.pixelSize: Theme.text_lg
                font.weight: Font.Bold
            }

            Hint {
                objectName: "cleanupImportError"
                Layout.fillWidth: true
                visible: (dialog.view.import_error ?? "") !== ""
                text: dialog.view.import_error ?? ""
                tone: "drop"
            }

            UiText {
                Layout.fillWidth: true
                visible: importPopup.data.file !== undefined
                text: (importPopup.data.file ?? "") + " · " + (importPopup.data.summary ?? "")
                wrapMode: Text.WordWrap
            }

            ScrollPane {
                id: importScroll

                Layout.fillWidth: true
                Layout.fillHeight: true
                visible: importPopup.data.file !== undefined
                clip: true
                contentWidth: availableWidth

                ColumnLayout {
                    width: importScroll.availableWidth
                    spacing: Theme.space_xs

                    Repeater {
                        model: importPopup.data.sets ?? []

                        delegate: UiText {
                            required property var modelData

                            Layout.fillWidth: true
                            text: modelData.name + " · " + modelData.count
                            font.pixelSize: Theme.text_sm
                        }
                    }

                    UiText {
                        Layout.fillWidth: true
                        visible: (importPopup.data.ocr ?? "") !== ""
                        text: Strings.f("cleanup.import.ocr", {"rules": importPopup.data.ocr ?? ""})
                        font.pixelSize: Theme.text_sm
                    }

                    UiText {
                        Layout.fillWidth: true
                        Layout.topMargin: Theme.space_md
                        visible: (importPopup.data.skipped_count ?? 0) > 0
                        text: Strings.n("cleanup.import.skipped", importPopup.data.skipped_count ?? 0)
                        color: Theme.change
                        font.pixelSize: Theme.text_sm
                    }

                    Repeater {
                        model: importPopup.data.skipped ?? []

                        delegate: UiText {
                            required property var modelData

                            Layout.fillWidth: true
                            text: modelData.where + ": " + modelData.text + " — " + modelData.reason
                            color: Theme.muted
                            font.pixelSize: Theme.text_xs
                            wrapMode: Text.WrapAnywhere
                        }
                    }
                }
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: Theme.space_md

                Item {
                    Layout.fillWidth: true
                }

                ActionButton {
                    text: Strings.t("common.cancel")
                    onClicked: importPopup.close()
                }

                ActionButton {
                    objectName: "cleanupImportConfirm"
                    kind: "primary"
                    visible: importPopup.data.file !== undefined
                    text: Strings.t("cleanup.dialog.make")
                    onClicked: {
                        dialog.editor.confirm_import()
                    }
                }
            }
        }
    }
}
