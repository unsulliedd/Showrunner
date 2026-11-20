import QtQuick
import QtQuick.Controls.Basic
import Showrunner

// The profile of the selected batch, with "edited" when its working copy differs; the menu switches it.
AbstractButton {
    id: pill

    implicitHeight: Theme.row_md
    implicitWidth: content.implicitWidth + Theme.space_lg + Theme.space_md
    enabled: app.has_batch
    hoverEnabled: true
    focusPolicy: Qt.StrongFocus
    Accessible.role: Accessible.ButtonMenu
    Accessible.name: Strings.t("top.profile") + " " + app.profile
    onClicked: menu.open()

    background: Rectangle {
        radius: Theme.radius_md
        color: pill.hovered && pill.enabled ? Theme.panel_3 : Theme.panel
        border.width: Theme.stroke
        border.color: pill.visualFocus ? Theme.control : Theme.line_strong
    }

    contentItem: Item {
        implicitWidth: content.implicitWidth
        implicitHeight: content.implicitHeight

        Row {
            id: content

            x: Theme.space_md
            anchors.verticalCenter: parent.verticalCenter
            spacing: Theme.space_md

            UiText {
                anchors.verticalCenter: parent.verticalCenter
                text: Strings.t("top.profile")
                color: Theme.faint
                font.pixelSize: Theme.text_xs
            }

            UiText {
                anchors.verticalCenter: parent.verticalCenter
                text: app.profile
                color: pill.enabled ? Theme.ink : Theme.muted
                font.weight: Font.DemiBold
            }

            Row {
                anchors.verticalCenter: parent.verticalCenter
                visible: app.profile_edited
                spacing: Theme.space_sm

                Rectangle {
                    anchors.verticalCenter: parent.verticalCenter
                    width: Theme.dot
                    height: Theme.dot
                    radius: Theme.dot / 2
                    color: Theme.change
                }

                UiText {
                    anchors.verticalCenter: parent.verticalCenter
                    text: Strings.t("top.edited")
                    color: Theme.change
                    font.pixelSize: Theme.text_xs
                }
            }

            Icon {
                anchors.verticalCenter: parent.verticalCenter
                name: "down"
                size: Theme.icon_sm
            }
        }
    }

    Menu {
        id: menu

        y: pill.height + Theme.space_sm
        padding: Theme.space_sm

        background: Rectangle {
            implicitWidth: Theme.menu_width
            radius: Theme.radius_md
            color: Theme.panel_2
            border.width: Theme.stroke
            border.color: Theme.line_strong
        }

        Instantiator {
            model: app.profiles

            delegate: MenuRow {
                required property string modelData

                text: modelData
                checkable: true
                checked: modelData === app.profile
                enabled: !app.profile_edited
                onTriggered: app.switch_profile(modelData)
            }

            onObjectAdded: (index, object) => menu.insertItem(index, object)
            onObjectRemoved: (index, object) => menu.removeItem(object)
        }

        MenuSeparator {
            contentItem: Rectangle {
                implicitHeight: Theme.stroke
                color: Theme.line
            }
        }

        MenuRow {
            text: Strings.t("profile.save")
            enabled: app.profile_edited && !app.profile_read_only
            onTriggered: app.save_profile()
        }

        MenuRow {
            text: Strings.t("profile.save_as")
            onTriggered: saveAs.open()
        }

        MenuRow {
            text: Strings.t("profile.revert")
            enabled: app.profile_edited
            onTriggered: app.ask_revert()
        }

        MenuSeparator {
            contentItem: Rectangle {
                implicitHeight: Theme.stroke
                color: Theme.line
            }
        }

        MenuRow {
            objectName: "manageProfiles"
            text: Strings.t("profile.manage")
            onTriggered: app.settings.open("profiles")
        }
    }

    SaveAsPopup {
        id: saveAs
    }
}
