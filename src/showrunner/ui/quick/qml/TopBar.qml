import QtQuick
import QtQuick.Layouts
import Showrunner

// The app name, the profile pill and the Home button, the search field in the middle, the drawer and settings buttons, the change
// count and the way to Review.
Item {
    id: bar

    property bool drawerOpen: false
    property alias search: search

    signal drawerToggled()
    signal reviewAsked()
    signal settingsAsked()

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

        // Home over the open library: nothing is closed, and a click on a row of the library comes back.
        IconButton {
            objectName: "homeButton"
            visible: app.loaded
            enabled: !app.home_shown
            iconName: "home"
            label: Strings.t("workspace.home")
            tip: Strings.t("workspace.home_tip")
            onClicked: app.go_home()
        }

        Item {
            Layout.fillWidth: true
        }

        Item {
            Layout.fillWidth: true
        }

        IconButton {
            iconName: "panel_bottom"
            label: Strings.t("top.drawer")
            tip: Strings.t("tip.top_drawer")
            active: bar.drawerOpen
            onClicked: bar.drawerToggled()
        }

        IconButton {
            objectName: "settingsButton"
            iconName: "sliders"
            label: Strings.t("top.settings")
            tip: Strings.t("tip.top_settings")
            onClicked: bar.settingsAsked()
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

    // The command palette's field: it finds files, tracks, tokens and actions. The library has its own filter.
    FindField {
        id: search

        objectName: "paletteField"
        anchors.centerIn: parent
        width: Theme.search_width
        placeholderText: Strings.t("top.search")
        hint: Strings.t("top.search_key")
        text: app.palette_query
        onTextEdited: app.palette_query = text
        onActiveFocusChanged: activeFocus ? finder.open() : finder.close()
        Keys.onDownPressed: finder.move(1)
        Keys.onUpPressed: finder.move(-1)
        Keys.onReturnPressed: finder.run(finder.current)
        Keys.onEnterPressed: finder.run(finder.current)
        Keys.onEscapePressed: {
            app.palette_query = ""
            focus = false
        }
    }

    CommandPalette {
        id: finder

        field: search
    }
}
