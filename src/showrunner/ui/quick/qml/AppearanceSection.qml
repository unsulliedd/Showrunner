import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import Showrunner

// Appearance: the theme, the three base colours with the roles derived from them and the contrast check, and the
// density. Every change repaints the window at once and is saved.
SettingsPage {
    id: page

    readonly property var look: app.settings.appearance

    title: Strings.t("prefs.appearance.title")

    actions: [
        ActionButton {
            kind: "ghost"
            text: Strings.t("prefs.appearance.export")
            onClicked: page.look.export_theme()
        },
        ActionButton {
            kind: "ghost"
            text: Strings.t("prefs.appearance.import")
            onClicked: page.look.import_theme()
        },
        ActionButton {
            objectName: "resetColours"
            kind: "ghost"
            text: Strings.t("prefs.appearance.reset")
            enabled: page.look.changed_colors
            onClicked: page.look.reset_colors()
        }
    ]

    SettingLabel {
        text: Strings.t("prefs.appearance.theme")
    }

    Segmented {
        objectName: "themeMode"
        Layout.fillWidth: true
        name: Strings.t("prefs.appearance.theme")
        current: page.look.mode
        model: [
            {"key": "dark", "label": Strings.t("prefs.appearance.mode.dark")},
            {"key": "light", "label": Strings.t("prefs.appearance.mode.light")},
            {"key": "system", "label": Strings.t("prefs.appearance.mode.system")}
        ]
        onPicked: key => page.look.set_mode(key)
    }

    Hint {
        text: page.look.mode !== "dark" ? Strings.t("prefs.appearance.light_hint") : ""
    }

    SettingLabel {
        text: Strings.t("prefs.appearance.bases")
    }

    Repeater {
        model: page.look.bases

        delegate: RowLayout {
            id: base

            required property var modelData
            property string problem: ""

            Layout.fillWidth: true
            spacing: Theme.space_lg

            AbstractButton {
                implicitWidth: Theme.row_md
                implicitHeight: Theme.row_md
                focusPolicy: Qt.StrongFocus
                Accessible.role: Accessible.Button
                Accessible.name: Strings.f("prefs.appearance.pick",
                                           {"name": Strings.t("prefs.appearance.base." + base.modelData.key)})
                onClicked: page.look.pick_base(base.modelData.key)

                background: Rectangle {
                    radius: Theme.radius_md
                    // The swatch shows the colour being chosen, so its fill is that colour rather than a role.
                    color: base.modelData.hex
                    border.width: parent.visualFocus ? Theme.stroke * 2 : Theme.stroke
                    border.color: parent.visualFocus ? Theme.control : Theme.line_strong
                }
            }

            ColumnLayout {
                Layout.fillWidth: true
                spacing: 0

                UiText {
                    text: Strings.t("prefs.appearance.base." + base.modelData.key)
                    font.weight: Font.Medium
                }

                Hint {
                    text: base.problem !== "" ? base.problem
                                              : Strings.t("prefs.appearance.base." + base.modelData.key + ".hint")
                    tone: base.problem !== "" ? "drop" : "muted"
                }
            }

            InputField {
                objectName: "base_" + base.modelData.key
                Layout.preferredWidth: Theme.swatch_width
                mono: true
                label: Strings.t("prefs.appearance.base." + base.modelData.key)
                text: base.modelData.hex
                onEditingFinished: {
                    if (text.toUpperCase() === base.modelData.hex)
                        return
                    base.problem = page.look.set_base(base.modelData.key, text) ? ""
                                                                                : Strings.t("prefs.appearance.hex_bad")
                }
            }
        }
    }

    SettingLabel {
        text: Strings.t("prefs.appearance.derived")
    }

    RowLayout {
        Layout.fillWidth: true
        spacing: Theme.space_sm

        Repeater {
            model: page.look.derived

            delegate: ColumnLayout {
                required property var modelData

                Layout.fillWidth: true
                spacing: Theme.space_sm

                Rectangle {
                    Layout.fillWidth: true
                    implicitHeight: Theme.row_sm
                    radius: Theme.radius_sm
                    color: parent.modelData.hex
                    border.width: Theme.stroke
                    border.color: Theme.line
                }

                UiText {
                    Layout.fillWidth: true
                    mono: true
                    text: parent.modelData.key
                    color: Theme.muted
                    font.pixelSize: Theme.text_xs
                    horizontalAlignment: Text.AlignHCenter
                }
            }
        }
    }

    RowLayout {
        objectName: "contrast"
        Layout.fillWidth: true
        spacing: Theme.space_md

        Icon {
            Layout.alignment: Qt.AlignTop
            name: page.look.contrast.length === 0 ? "check" : "alert"
            size: Theme.icon_sm
            color: page.look.contrast.length === 0 ? Theme.add : Theme.change
        }

        ColumnLayout {
            Layout.fillWidth: true
            spacing: Theme.space_xs

            Hint {
                visible: page.look.contrast.length === 0
                text: Strings.t("prefs.appearance.contrast_ok")
            }

            Repeater {
                model: page.look.contrast

                delegate: Hint {
                    required property var modelData

                    text: modelData.text
                    tone: "change"
                }
            }
        }
    }

    SettingLabel {
        text: Strings.t("prefs.appearance.density")
    }

    Segmented {
        objectName: "density"
        Layout.fillWidth: true
        name: Strings.t("prefs.appearance.density")
        current: page.look.density
        model: [
            {"key": "comfortable", "label": Strings.t("prefs.appearance.density.comfortable")},
            {"key": "compact", "label": Strings.t("prefs.appearance.density.compact")}
        ]
        onPicked: key => page.look.set_density(key)
    }

    Hint {
        text: Strings.t("prefs.appearance.density_hint")
    }

    Hint {
        text: page.look.message
        tone: page.look.message_tone
    }
}
