import QtQuick
import QtQuick.Layouts
import Showrunner

// The app name, the profile pill, the search field in the middle, the drawer and settings buttons, the change
// count and the way to Review.
Item {
    id: bar

    property bool drawerOpen: false
    property alias search: search

    signal drawerToggled()
    signal reviewAsked()

    implicitHeight: Theme.top_bar

    RowLayout {
        anchors.fill: parent
        anchors.leftMargin: Theme.space_lg + Theme.space_xs
        anchors.rightMargin: Theme.space_md + Theme.space_xs
        spacing: Theme.space_lg

        Row {
            spacing: Theme.space_md

            Image {
                anchors.verticalCenter: parent.verticalCenter
                width: Theme.icon_lg
                height: Theme.icon_lg
                sourceSize: Qt.size(Theme.icon_lg, Theme.icon_lg)
                source: "image://icon/logo/" + Theme.ink.toString().substring(1, 7) + "/"
                        + Theme.control.toString().substring(1, 7)
                Accessible.ignored: true
            }

            UiText {
                anchors.verticalCenter: parent.verticalCenter
                text: Strings.t("app.name")
                font.pixelSize: Theme.text_lg
                font.weight: Font.Bold
            }
        }

        ProfilePill {}

        Item {
            Layout.fillWidth: true
        }

        Item {
            Layout.fillWidth: true
        }

        IconButton {
            iconName: "panel_bottom"
            label: Strings.t("top.drawer")
            active: bar.drawerOpen
            onClicked: bar.drawerToggled()
        }

        IconButton {
            iconName: "sliders"
            label: Strings.t("top.settings")
            enabled: false
        }

        UiText {
            objectName: "planning"
            visible: app.planning && !app.jobs.running
            text: Strings.t("top.planning")
            color: Theme.faint
            font.pixelSize: Theme.text_sm
        }

        UiText {
            visible: !app.jobs.running
            text: app.change_text
            color: Theme.muted
            font.pixelSize: Theme.text_md
        }

        ActionButton {
            visible: !app.jobs.running
            text: app.change_count > 0 ? Strings.t("top.review_apply") : Strings.t("top.review")
            kind: app.change_count > 0 ? "primary" : "outline"
            iconName: app.change_count > 0 ? "arrow" : ""
            enabled: app.has_batch
            onClicked: bar.reviewAsked()
        }

        Rectangle {
            objectName: "jobProgress"
            visible: app.jobs.running
            implicitWidth: progress.implicitWidth + 2 * Theme.space_lg
            implicitHeight: Theme.row_md
            radius: Theme.radius_md
            color: Theme.panel
            border.width: Theme.stroke
            border.color: Theme.line_strong

            RowLayout {
                id: progress

                anchors.centerIn: parent
                spacing: Theme.space_md

                Icon {
                    name: "resume"
                    color: Theme.control
                }

                UiText {
                    text: Strings.t("top.applying")
                    font.weight: Font.DemiBold
                }

                UiText {
                    text: app.jobs.view.count || ""
                    color: Theme.muted
                }

                ProgressLine {
                    Layout.preferredWidth: Theme.progress_width
                    value: app.jobs.view.fraction || 0
                }
            }
        }

        ActionButton {
            visible: app.jobs.running
            kind: "outline"
            text: Strings.t("jobs.cancel")
            onClicked: app.jobs.cancel()
        }
    }

    FindField {
        id: search

        anchors.centerIn: parent
        width: Theme.search_width
        placeholderText: Strings.t("top.search")
        hint: Strings.t("top.search_key")
        text: app.filter_text
        onTextEdited: app.filter_text = text
    }
}
