import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import Showrunner

// Profiles: every profile, and for the picked one its file actions and the settings kept with it (implied flags,
// where originals go, the keep folder and the new file's name). Changes are written to the profile at once.
SettingsPage {
    id: page

    readonly property var profile: app.settings.profile
    readonly property bool editable: profile.editable === true

    title: Strings.t("prefs.profiles.title")
    lead: Strings.t("prefs.profiles.lead")

    actions: [
        ActionButton {
            kind: "ghost"
            iconName: "upload"
            text: Strings.t("prefs.profiles.import")
            enabled: !app.settings.profiles_locked
            onClicked: app.settings.import_profile()
        }
    ]

    RowLayout {
        Layout.fillWidth: true
        Layout.topMargin: Theme.space_md
        spacing: Theme.space_xl

        Rectangle {
            Layout.preferredWidth: Theme.menu_width
            Layout.alignment: Qt.AlignTop
            implicitHeight: list.contentHeight + 2 * Theme.space_sm
            radius: Theme.radius_md
            color: Theme.well
            border.width: Theme.stroke
            border.color: Theme.line

            ListView {
                id: list

                objectName: "profileList"
                anchors.fill: parent
                anchors.margins: Theme.space_sm
                interactive: false
                model: app.settings.profiles
                currentIndex: app.settings.profiles.findIndex(entry => entry.name === app.settings.picked)
                activeFocusOnTab: true
                Accessible.role: Accessible.List
                Accessible.name: Strings.t("prefs.profiles.list")
                Keys.onUpPressed: if (currentIndex > 0) app.settings.pick(model[currentIndex - 1].name)
                Keys.onDownPressed: if (currentIndex < count - 1) app.settings.pick(model[currentIndex + 1].name)

                delegate: AbstractButton {
                    id: entry

                    required property var modelData
                    readonly property bool current: modelData.name === app.settings.picked

                    width: ListView.view.width
                    implicitHeight: Theme.row_md
                    hoverEnabled: true
                    focusPolicy: Qt.NoFocus
                    Accessible.role: Accessible.ListItem
                    Accessible.name: modelData.name
                    Accessible.selected: current
                    onClicked: app.settings.pick(modelData.name)

                    background: Rectangle {
                        radius: Theme.radius_sm
                        color: entry.current ? Theme.select : entry.hovered ? Theme.panel_2 : "transparent"
                        border.width: entry.current && list.activeFocus ? Theme.stroke : 0
                        border.color: Theme.control
                    }

                    contentItem: RowLayout {
                        spacing: Theme.space_sm

                        UiText {
                            Layout.fillWidth: true
                            Layout.leftMargin: Theme.space_md
                            text: entry.modelData.name
                            font.weight: entry.current ? Font.DemiBold : Font.Normal
                        }

                        UiText {
                            Layout.rightMargin: Theme.space_md
                            visible: entry.modelData.builtin || entry.modelData.used
                            text: entry.modelData.used ? Strings.t("prefs.profiles.in_use")
                                                       : Strings.t("prefs.profiles.built_in")
                            color: entry.modelData.used ? Theme.control : Theme.faint
                            font.pixelSize: Theme.text_xs
                        }
                    }
                }
            }
        }

        ColumnLayout {
            Layout.fillWidth: true
            Layout.alignment: Qt.AlignTop
            spacing: Theme.space_md

            UiText {
                Layout.fillWidth: true
                text: page.profile.name || ""
                font.pixelSize: Theme.text_lg
                font.weight: Font.Bold
            }

            Hint {
                text: page.profile.batches > 0 ? Strings.n("prefs.profiles.followed", page.profile.batches) : ""
            }

            Flow {
                Layout.fillWidth: true
                spacing: Theme.space_sm

                ActionButton {
                    text: Strings.t("prefs.profiles.rename")
                    enabled: page.editable
                    onClicked: {
                        naming.heading = Strings.f("prefs.profiles.rename_title", {"name": page.profile.name})
                        naming.action = Strings.t("prefs.profiles.rename_yes")
                        naming.initial = page.profile.name
                        naming.submit = name => app.settings.rename(name)
                        naming.open()
                    }
                }

                ActionButton {
                    text: Strings.t("prefs.profiles.duplicate")
                    enabled: !app.settings.profiles_locked && page.profile.readable === true
                    onClicked: {
                        naming.heading = Strings.f("prefs.profiles.duplicate_title", {"name": page.profile.name})
                        naming.action = Strings.t("prefs.profiles.duplicate_yes")
                        naming.initial = ""
                        naming.submit = name => app.settings.duplicate(name)
                        naming.open()
                    }
                }

                ActionButton {
                    text: Strings.t("prefs.profiles.export")
                    enabled: page.profile.readable === true
                    onClicked: app.settings.export_profile()
                }

                ActionButton {
                    objectName: "deleteProfile"
                    text: Strings.t("prefs.profiles.delete")
                    enabled: page.editable
                    onClicked: remove.open()
                }
            }

            Hint {
                text: page.profile.readable === false ? Strings.t("prefs.profiles.unreadable")
                    : app.settings.profiles_locked ? Strings.t("prefs.profiles.locked")
                    : page.profile.builtin ? Strings.t("prefs.profiles.read_only") : ""
                tone: page.profile.readable === false ? "drop" : "muted"
            }

            Hint {
                objectName: "profileMessage"
                text: app.settings.message
                tone: app.settings.message_tone
            }
        }
    }

    RowLayout {
        Layout.fillWidth: true
        Layout.topMargin: Theme.space_lg
        visible: page.profile.readable === true
        spacing: Theme.space_lg

        ColumnLayout {
            Layout.fillWidth: true
            spacing: Theme.space_xs

            UiText {
                text: Strings.t("prefs.profiles.flags")
                font.weight: Font.DemiBold
            }

            Hint {
                text: Strings.t("prefs.profiles.flags_hint")
            }
        }

        Toggle {
            objectName: "flagsFromNames"
            label: Strings.t("prefs.profiles.flags")
            enabled: page.editable
            checked: page.profile.flags_from_names === true
            onToggled: app.settings.set_flags_from_names(checked)
        }
    }

    ColumnLayout {
        Layout.fillWidth: true
        visible: page.profile.readable === true
        spacing: Theme.space_md

        SettingLabel {
            text: Strings.t("prefs.profiles.originals")
        }

        Segmented {
            objectName: "originals"
            Layout.fillWidth: true
            enabled: page.editable
            name: Strings.t("prefs.profiles.originals")
            current: page.profile.original || ""
            model: [
                {"key": "recycle", "label": Strings.t("prefs.profiles.original.recycle")},
                {"key": "keep", "label": Strings.t("prefs.profiles.original.keep")}
            ]
            onPicked: key => app.settings.set_original(key)
        }

        Hint {
            text: Strings.t("prefs.profiles.originals_hint")
        }

        SettingLabel {
            text: Strings.t("prefs.profiles.keep_folder")
            note: Strings.t("prefs.profiles.keep_folder_hint")
        }

        InputField {
            objectName: "keepFolder"
            Layout.fillWidth: true
            mono: true
            enabled: page.editable
            label: Strings.t("prefs.profiles.keep_folder")
            text: page.profile.keep_folder || ""
            onEditingFinished: if (text !== page.profile.keep_folder) app.settings.set_keep_folder(text)
        }

        Hint {
            text: (page.profile.problems || {}).keep_folder || ""
            tone: "drop"
        }

        SettingLabel {
            text: Strings.t("prefs.profiles.suffix")
            note: Strings.t("prefs.profiles.suffix_hint")
        }

        InputField {
            objectName: "suffix"
            Layout.fillWidth: true
            mono: true
            enabled: page.editable
            label: Strings.t("prefs.profiles.suffix")
            placeholderText: Strings.t("prefs.profiles.suffix_placeholder")
            font.italic: text === ""
            rightPadding: suffixTag.implicitWidth + 2 * Theme.space_md
            text: page.profile.suffix || ""
            onEditingFinished: if (text !== page.profile.suffix) app.settings.set_suffix(text)

            UiText {
                id: suffixTag

                anchors.right: parent.right
                anchors.rightMargin: Theme.space_md
                anchors.verticalCenter: parent.verticalCenter
                text: Strings.t("prefs.profiles.suffix_label")
                color: Theme.faint
                font.pixelSize: Theme.text_sm
            }
        }

        Hint {
            text: (page.profile.problems || {}).suffix || ""
            tone: "drop"
        }
    }

    SaveAsPopup {
        id: naming
    }

    ConfirmPopup {
        id: remove

        heading: Strings.f("prefs.profiles.delete_title", {"name": page.profile.name || ""})
        text: Strings.t("prefs.profiles.delete_text")
        yes: Strings.t("prefs.profiles.delete_yes")
        danger: true
        onAccepted: app.settings.delete()
    }
}
