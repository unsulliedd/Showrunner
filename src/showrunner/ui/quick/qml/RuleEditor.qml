import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import Showrunner

// The form of a hand-written track rule, in the Rules panel in place of the list. It draws what `app.rule_editor.form`
// holds and sends every change to a slot; the draft, its problems and what Save does live in Python. A field is
// sent as it is typed, so Save's state and the problems under the fields are never behind. Ctrl+Return saves from
// any field, Return saves from a text field, Escape cancels.
FocusScope {
    id: editor

    readonly property var form: app.rule_editor.form
    // The lists of choices never change while the editor is open, so the segments keep their focus.
    readonly property var choices: app.rule_editor.options

    objectName: "ruleEditor"
    Keys.onEscapePressed: app.rule_editor.cancel()
    Keys.onPressed: event => {
        if ((event.key === Qt.Key_Return || event.key === Qt.Key_Enter) && (event.modifiers & Qt.ControlModifier)) {
            app.rule_editor.save()
            event.accepted = true
        }
    }
    Component.onCompleted: label.forceActiveFocus()

    component Heading: UiText {
        Layout.fillWidth: true
        Layout.topMargin: Theme.space_md
        color: Theme.faint
        font.pixelSize: Theme.text_xs
        font.weight: Font.DemiBold
        font.letterSpacing: Theme.stroke
        font.capitalization: Font.AllUppercase
    }

    component Name: UiText {
        Layout.fillWidth: true
        Layout.topMargin: Theme.space_sm
        color: Theme.muted
        font.pixelSize: Theme.text_sm
        font.weight: Font.Medium
    }

    // The problems of one field, in place under it.
    component Problems: Repeater {
        delegate: Hint {
            required property var modelData

            text: modelData
            tone: "drop"
            font.pixelSize: Theme.text_xs
        }
    }

    // The languages or codecs of the batch, each a button that puts it into the field or takes it out.
    component Picks: Flow {
        id: picks

        property string field
        property var items: []

        Layout.fillWidth: true
        spacing: Theme.space_xs

        Repeater {
            model: picks.items.length

            delegate: ActionButton {
                id: pick

                required property int index
                readonly property var item: picks.items[index]

                objectName: picks.field + "Pick_" + index
                kind: checked ? "outline" : "ghost"
                size: Theme.row_sm
                checkable: true
                checked: item.on
                text: item.text
                onClicked: app.rule_editor.toggle_pick(picks.field, index)
            }
        }
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: Theme.space_md

        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.space_md

            UiText {
                Layout.fillWidth: true
                text: editor.form.title
                font.pixelSize: Theme.text_lg
                font.weight: Font.DemiBold
            }

            UiText {
                text: editor.form.fits
                color: Theme.faint
                font.pixelSize: Theme.text_xs
            }
        }

        RuleSentence {
            Layout.fillWidth: true
            parts: editor.form.parts
        }

        ScrollPane {
            id: scroll

            objectName: "ruleScroll"
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            contentWidth: availableWidth

            ColumnLayout {
                width: scroll.availableWidth
                spacing: Theme.space_sm

                Name {
                    text: Strings.t("rules.editor.field.label")
                }

                InputField {
                    id: label

                    objectName: "ruleLabel"
                    Layout.fillWidth: true
                    label: Strings.t("rules.editor.field.label")
                    placeholderText: Strings.t("rules.editor.label_placeholder")
                    text: editor.form.label
                    onTextEdited: app.rule_editor.set_text("label", text)
                    onAccepted: app.rule_editor.save()
                }

                Hint {
                    text: Strings.t("rules.editor.label_help")
                    font.pixelSize: Theme.text_xs
                }

                Heading {
                    text: Strings.t("rules.editor.match")
                }

                Name {
                    text: Strings.t("rules.editor.field.kind")
                }

                Segmented {
                    objectName: "ruleKind"
                    Layout.fillWidth: true
                    name: Strings.t("rules.editor.field.kind")
                    model: editor.choices.kinds
                    current: editor.form.kind
                    onPicked: key => app.rule_editor.set_kind(key)
                }

                Name {
                    text: Strings.t("rules.editor.field.languages")
                }

                InputField {
                    objectName: "ruleLanguages"
                    invalid: (editor.form.problems.languages || []).length > 0
                    Layout.fillWidth: true
                    mono: true
                    label: Strings.t("rules.editor.field.languages")
                    placeholderText: Strings.t("rules.editor.languages_placeholder")
                    text: editor.form.languages
                    onTextEdited: app.rule_editor.set_text("languages", text)
                    onAccepted: app.rule_editor.save()
                }

                Problems {
                    model: editor.form.problems.languages || []
                }

                Hint {
                    visible: text !== ""
                    text: editor.form.language_names
                    tone: "add"
                }

                Hint {
                    text: Strings.t("rules.editor.languages_help")
                    font.pixelSize: Theme.text_xs
                }

                Picks {
                    field: "languages"
                    items: editor.form.language_picks
                }

                Name {
                    text: Strings.t("rules.editor.field.codecs")
                }

                InputField {
                    objectName: "ruleCodecs"
                    Layout.fillWidth: true
                    mono: true
                    label: Strings.t("rules.editor.field.codecs")
                    placeholderText: Strings.t("rules.editor.codecs_placeholder")
                    text: editor.form.codecs
                    onTextEdited: app.rule_editor.set_text("codecs", text)
                    onAccepted: app.rule_editor.save()
                }

                Hint {
                    text: Strings.t("rules.editor.codecs_help")
                    font.pixelSize: Theme.text_xs
                }

                Picks {
                    field: "codecs"
                    items: editor.form.codec_picks
                }

                Name {
                    visible: editor.form.channels_shown
                    text: Strings.t("rules.editor.field.channels")
                }

                RowLayout {
                    Layout.fillWidth: true
                    visible: editor.form.channels_shown
                    spacing: Theme.space_md

                    InputField {
                        objectName: "ruleLow"
                        invalid: (editor.form.problems.channels || []).length > 0
                        Layout.fillWidth: true
                        Layout.preferredWidth: 1
                        mono: true
                        label: Strings.t("rules.editor.channels_low")
                        placeholderText: Strings.t("rules.editor.channels_low")
                        text: editor.form.low
                        maximumLength: editor.choices.digits
                        validator: IntValidator {
                            bottom: 0
                        }
                        onTextEdited: app.rule_editor.set_text("low", text)
                        onAccepted: app.rule_editor.save()
                    }

                    InputField {
                        objectName: "ruleHigh"
                        invalid: (editor.form.problems.channels || []).length > 0
                        Layout.fillWidth: true
                        Layout.preferredWidth: 1
                        mono: true
                        label: Strings.t("rules.editor.channels_high")
                        placeholderText: Strings.t("rules.editor.channels_high")
                        text: editor.form.high
                        maximumLength: editor.choices.digits
                        validator: IntValidator {
                            bottom: 0
                        }
                        onTextEdited: app.rule_editor.set_text("high", text)
                        onAccepted: app.rule_editor.save()
                    }
                }

                Problems {
                    model: editor.form.problems.channels || []
                }

                Name {
                    text: Strings.t("rules.editor.field.name")
                }

                InputField {
                    objectName: "ruleName"
                    invalid: (editor.form.problems.name || []).length > 0
                    Layout.fillWidth: true
                    mono: true
                    label: Strings.t("rules.editor.field.name")
                    placeholderText: Strings.t("rules.editor.name_placeholder")
                    text: editor.form.name
                    onTextEdited: app.rule_editor.set_text("name", text)
                    onAccepted: app.rule_editor.save()
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: Theme.space_md

                    Toggle {
                        objectName: "ruleRegex"
                        label: Strings.t("rules.editor.regex")
                        checked: editor.form.regex
                        onToggled: app.rule_editor.set_regex(checked)
                    }

                    UiText {
                        Layout.fillWidth: true
                        text: Strings.t("rules.editor.regex")
                        color: Theme.muted
                        font.pixelSize: Theme.text_sm
                    }
                }

                Problems {
                    model: editor.form.problems.name || []
                }

                Hint {
                    text: Strings.t("rules.editor.name_help")
                    font.pixelSize: Theme.text_xs
                }

                Name {
                    text: Strings.t("rules.editor.field.flags")
                }

                Repeater {
                    model: editor.choices.flags.length

                    delegate: RowLayout {
                        id: test

                        required property int index
                        readonly property var flag: editor.choices.flags[index]

                        Layout.fillWidth: true
                        spacing: Theme.space_md

                        UiText {
                            Layout.fillWidth: true
                            Layout.preferredWidth: 4
                            text: test.flag.label
                        }

                        Segmented {
                            objectName: "ruleTest_" + test.flag.key
                            Layout.fillWidth: true
                            Layout.preferredWidth: 5
                            name: test.flag.label
                            model: editor.choices.tests
                            current: editor.form.tests[test.flag.key]
                            onPicked: key => app.rule_editor.set_test(test.flag.key, key)
                        }
                    }
                }

                Name {
                    text: Strings.t("rules.editor.field.source")
                }

                Segmented {
                    objectName: "ruleSource"
                    Layout.fillWidth: true
                    name: Strings.t("rules.editor.field.source")
                    model: editor.form.paired_offered ? editor.choices.sources_with_paired : editor.choices.sources
                    current: editor.form.source
                    onPicked: key => app.rule_editor.set_source(key)
                }

                Problems {
                    model: editor.form.problems.source || []
                }

                Heading {
                    text: Strings.t("rules.editor.then")
                }

                Name {
                    text: Strings.t("rules.editor.field.verdict")
                }

                Segmented {
                    objectName: "ruleVerdict"
                    Layout.fillWidth: true
                    name: Strings.t("rules.editor.field.verdict")
                    model: editor.choices.verdicts
                    current: editor.form.verdict
                    onPicked: key => app.rule_editor.set_verdict(key)
                }

                Hint {
                    text: Strings.t("rules.editor.verdict_help")
                    font.pixelSize: Theme.text_xs
                }

                Hint {
                    visible: !editor.form.flags_shown
                    text: Strings.t("rules.editor.no_flags")
                }

                Repeater {
                    model: editor.form.flags_shown ? editor.choices.actions.length : 0

                    delegate: RowLayout {
                        id: action

                        required property int index
                        readonly property var flag: editor.choices.actions[index]

                        Layout.fillWidth: true
                        spacing: Theme.space_md

                        UiText {
                            Layout.fillWidth: true
                            Layout.preferredWidth: 4
                            text: action.flag.label
                        }

                        Segmented {
                            objectName: "ruleAction_" + action.flag.key
                            Layout.fillWidth: true
                            Layout.preferredWidth: 5
                            name: action.flag.label
                            model: editor.choices.shapes
                            current: editor.form[action.flag.key]
                            onPicked: key => app.rule_editor.set_action(action.flag.key, key)
                        }
                    }
                }

                Hint {
                    visible: editor.form.flags_shown
                    text: Strings.t("rules.editor.action_help")
                    font.pixelSize: Theme.text_xs
                }
            }
        }

        Hint {
            objectName: "ruleNote"
            text: editor.form.note
            tone: editor.form.note_tone
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.space_md

            ActionButton {
                objectName: "saveRule"
                kind: "primary"
                enabled: editor.form.can_save
                iconName: "check"
                text: Strings.t("rules.editor.save")
                onClicked: app.rule_editor.save()
            }

            ActionButton {
                objectName: "cancelRule"
                kind: "ghost"
                text: Strings.t("rules.editor.cancel")
                onClicked: app.rule_editor.cancel()
            }
        }

        Hint {
            text: Strings.t("rules.editor.keys")
            color: Theme.faint
            font.pixelSize: Theme.text_xs
        }
    }
}
