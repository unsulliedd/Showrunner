import QtQuick
import QtQuick.Controls.Basic
import Showrunner

// The window: top bar, then the library, the workspace with its drawer, and the side panel in resizable splits,
// then the status bar. Before anything is loaded the workspace is the home screen.
ApplicationWindow {
    id: window

    property string place: "overview"
    property bool drawerOpen: false
    readonly property bool sideShown: app.has_batch && app.side_tabs(place).length > 0

    // The start size is set once: a binding would snap the window back each time Appearance changes the theme.
    Component.onCompleted: {
        width = Theme.quick_window_width
        height = Theme.quick_window_height
    }
    minimumWidth: Theme.window_min_width
    minimumHeight: Theme.window_min_height
    visible: true
    title: Strings.t("app.name")
    color: Theme.ground
    font.family: Theme.font
    font.pixelSize: Theme.text_md

    header: TopBar {
        id: top

        drawerOpen: window.drawerOpen
        onDrawerToggled: window.drawerOpen = !window.drawerOpen
        onReviewAsked: window.place = "review"
        onSettingsAsked: settings.show(settings.section)
    }

    footer: StatusBar {}

    Shortcut {
        sequence: app.settings.keys.palette
        onActivated: {
            top.search.forceActiveFocus()
            top.search.selectAll()
        }
    }

    Shortcut {
        sequence: app.settings.keys.settings
        onActivated: settings.show(settings.section)
    }

    component Handle: Rectangle {
        implicitWidth: Theme.panel_gap
        implicitHeight: Theme.panel_gap
        color: "transparent"

        Rectangle {
            anchors.centerIn: parent
            width: parent.width > parent.height ? Theme.handle_length : Theme.underline
            height: parent.width > parent.height ? Theme.underline : Theme.handle_length
            radius: Theme.underline / 2
            color: Theme.control
            visible: parent.SplitHandle.hovered || parent.SplitHandle.pressed
        }
    }

    SplitView {
        id: columns

        anchors.fill: parent
        anchors.leftMargin: Theme.panel_gap
        anchors.rightMargin: Theme.panel_gap
        orientation: Qt.Horizontal
        handle: Handle {}
        onResizingChanged: if (!resizing) app.save_panel_state("columns", saveState())
        Component.onCompleted: restoreState(app.panel_state("columns"))

        LibraryPanel {
            SplitView.preferredWidth: Theme.library_width
            SplitView.minimumWidth: Theme.panel_min_width
        }

        SplitView {
            id: rows

            SplitView.fillWidth: true
            SplitView.minimumWidth: Theme.workspace_min_width
            orientation: Qt.Vertical
            handle: Handle {}
            onResizingChanged: if (!resizing) app.save_panel_state("rows", saveState())
            Component.onCompleted: restoreState(app.panel_state("rows"))

            Item {
                SplitView.fillHeight: true

                Home {
                    id: home

                    anchors.fill: parent
                    visible: !app.loaded
                }

                Workspace {
                    anchors.fill: parent
                    visible: app.loaded && app.has_batch
                    place: window.place
                    onPlacePicked: key => window.place = key
                }

                Panel {
                    anchors.fill: parent
                    visible: app.loaded && !app.has_batch

                    Placeholder {
                        anchors.fill: parent
                        iconName: "folder"
                        title: Strings.t("workspace.none.title")
                        lead: Strings.t("workspace.none.lead")
                    }
                }
            }

            BottomDrawer {
                id: drawer

                objectName: "drawer"
                visible: window.drawerOpen
                SplitView.preferredHeight: Theme.drawer_height
                SplitView.minimumHeight: Theme.drawer_tabs * 2
                onFolded: window.drawerOpen = false
            }
        }

        SidePanel {
            objectName: "sidePanel"
            visible: window.sideShown
            // The Rules and Tokens of a batch being applied wait until its job ends.
            enabled: !app.locked
            place: window.place
            SplitView.preferredWidth: Theme.inspector_width
            SplitView.minimumWidth: Theme.panel_min_width
        }
    }

    // The drawer opens on its Jobs tab when a job starts.
    Connections {
        target: app.jobs

        function onStarted() {
            drawer.tab = "jobs"
            window.drawerOpen = true
        }
    }

    JobOffer {}

    SettingsDialog {
        id: settings
    }

    // "Manage profiles…" in the pill and "Get it" anywhere open Settings on their section.
    Connections {
        target: app.settings

        function onOpen_asked(section) {
            settings.show(section)
        }
    }

    // A palette result that needs the window: a place, or the drawer.
    Connections {
        target: app

        function onPalette_asked(what, key) {
            if (what === "place")
                window.place = key
            else if (what === "drawer")
                window.drawerOpen = !window.drawerOpen
        }
    }

    DropArea {
        anchors.fill: parent
        onEntered: drag => {
            drag.accepted = drag.hasUrls
            home.dropping = drag.hasUrls
        }
        onExited: home.dropping = false
        onDropped: drop => {
            home.dropping = false
            app.add_urls(drop.urls)
        }
    }
}
