import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import Showrunner

// Settings: a modal dialog over the window with a section list on the left and the section on the right. Escape or
// a click beside it closes it; Up, Down, Home and End move between sections while the list has focus. A window
// narrower than `settings_rail_below` shows the list as a rail of icons. Everything applies at once.
Popup {
    id: dialog

    property string section: "general"
    readonly property var sections: app.settings.sections
    readonly property bool rail: parent !== null && parent.width < Theme.settings_rail_below
    readonly property var pages: ({
        "general": "GeneralSection.qml",
        "profiles": "ProfilesSection.qml",
        "programs": "ProgramsSection.qml",
        "ai": "AiSection.qml",
        "appearance": "AppearanceSection.qml",
        "shortcuts": "ShortcutsSection.qml",
        "about": "AboutSection.qml"
    })

    objectName: "settings"
    parent: Overlay.overlay
    anchors.centerIn: parent
    width: Math.min(Theme.settings_width, parent.width - 2 * Theme.space_2xl)
    height: Math.min(Theme.settings_height, parent.height - 2 * Theme.space_2xl)
    padding: 0
    modal: true
    focus: true
    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside

    function show(key) {
        section = key
        open()
    }

    function step(to) {
        section = sections[Math.max(0, Math.min(sections.length - 1, to))].key
    }

    onOpened: {
        nav.forceActiveFocus()
        app.settings.opened(section)
    }
    onSectionChanged: if (opened) app.settings.opened(section)
    onClosed: app.settings.closed()

    Overlay.modal: Rectangle {
        color: Theme.ground
        opacity: Theme.dim_percent / 100  // the window stays readable behind the dialog
    }

    background: Rectangle {
        radius: Theme.radius_lg
        color: Theme.panel
        border.width: Theme.stroke
        border.color: Theme.line_strong
    }

    contentItem: ColumnLayout {
        spacing: 0
        Accessible.role: Accessible.Dialog
        Accessible.name: Strings.t("prefs.title")

        RowLayout {
            Layout.fillWidth: true
            Layout.preferredHeight: Theme.top_bar + Theme.space_md
            Layout.leftMargin: Theme.space_xl
            Layout.rightMargin: Theme.space_md

            UiText {
                Layout.fillWidth: true
                text: Strings.t("prefs.title")
                font.pixelSize: Theme.text_lg
                font.weight: Font.Bold
                Accessible.role: Accessible.Heading
            }

            IconButton {
                objectName: "closeSettings"
                iconName: "x"
                label: Strings.t("prefs.close")
                tip: Strings.t("tip.settings_close")
                onClicked: dialog.close()
            }
        }

        Rectangle {
            Layout.fillWidth: true
            implicitHeight: Theme.stroke
            color: Theme.line
        }

        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 0

            ColumnLayout {
                Layout.fillHeight: true
                // A child that fills its width would make this column fill the row too.
                Layout.fillWidth: false
                Layout.preferredWidth: dialog.rail ? Theme.row_lg + 2 * Theme.space_md : Theme.settings_nav_width
                spacing: 0

                ListView {
                    id: nav

                    objectName: "settingsNav"
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    Layout.margins: Theme.space_md
                    model: dialog.sections
                    currentIndex: dialog.sections.findIndex(entry => entry.key === dialog.section)
                    spacing: Theme.space_xs
                    focus: true
                    boundsBehavior: Flickable.StopAtBounds
                    Accessible.role: Accessible.List
                    Accessible.name: Strings.t("prefs.sections")
                    Keys.onPressed: event => {
                        const moves = {
                            [Qt.Key_Up]: nav.currentIndex - 1,
                            [Qt.Key_Down]: nav.currentIndex + 1,
                            [Qt.Key_Home]: 0,
                            [Qt.Key_End]: dialog.sections.length - 1
                        }
                        if (moves[event.key] !== undefined) {
                            dialog.step(moves[event.key])
                            event.accepted = true
                        }
                    }

                    delegate: AbstractButton {
                        id: entry

                        required property var modelData
                        required property int index
                        readonly property bool current: modelData.key === dialog.section

                        width: ListView.view.width
                        implicitHeight: Theme.row_lg
                        hoverEnabled: true
                        focusPolicy: Qt.NoFocus
                        Accessible.role: Accessible.ListItem
                        Accessible.name: modelData.label
                        Accessible.selected: current
                        ToolTip.visible: dialog.rail && hovered
                        ToolTip.text: modelData.label
                        onClicked: {
                            dialog.step(index)
                            nav.forceActiveFocus()
                        }

                        background: Rectangle {
                            radius: Theme.radius_md
                            color: entry.current ? Theme.select : entry.hovered ? Theme.panel_2 : "transparent"
                            border.width: entry.current && nav.activeFocus ? Theme.stroke : 0
                            border.color: Theme.control
                        }

                        contentItem: RowLayout {
                            spacing: Theme.space_lg

                            Icon {
                                Layout.leftMargin: dialog.rail ? (entry.width - Theme.icon_md) / 2 : Theme.space_md
                                name: entry.modelData.icon
                                size: Theme.icon_md
                                color: entry.current ? Theme.ink : Theme.muted
                            }

                            UiText {
                                Layout.fillWidth: true
                                visible: !dialog.rail
                                text: entry.modelData.label
                                color: entry.current ? Theme.ink : Theme.muted
                                font.weight: entry.current ? Font.DemiBold : Font.Medium
                            }
                        }
                    }
                }

                Rectangle {
                    Layout.fillWidth: true
                    Layout.leftMargin: Theme.space_md
                    Layout.rightMargin: Theme.space_md
                    implicitHeight: Theme.stroke
                    color: Theme.line
                }

                UiText {
                    Layout.fillWidth: true
                    Layout.margins: Theme.space_lg
                    text: dialog.rail ? app.settings.version
                                      : Strings.f("prefs.version", {"version": app.settings.version})
                    color: Theme.muted
                    font.pixelSize: Theme.text_sm
                    horizontalAlignment: dialog.rail ? Text.AlignHCenter : Text.AlignLeft
                }
            }

            Rectangle {
                Layout.fillHeight: true
                implicitWidth: Theme.stroke
                color: Theme.line
            }

            Loader {
                id: page

                Layout.fillWidth: true
                Layout.fillHeight: true
                source: dialog.pages[dialog.section]
            }

            Connections {
                target: page.item
                ignoreUnknownSignals: true

                function onGoTo(key) {
                    dialog.section = key
                }
            }
        }
    }
}
