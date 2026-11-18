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

    // The window's place while it is neither maximized nor minimized, and whether it was maximized, as last seen.
    property rect normal: Qt.rect(x, y, width, height)
    property bool maximized: false

    // The start size is set once: a binding would snap the window back each time Appearance changes the theme.
    // The place of the last session comes from the controller, already moved onto a screen that exists now.
    Component.onCompleted: {
        width = Theme.quick_window_width
        height = Theme.quick_window_height
        const saved = app.window_state()
        if (saved.width !== undefined) {
            x = saved.x
            y = saved.y
            width = saved.width
            height = saved.height
            if (saved.maximized)
                visibility = Window.Maximized
        }
        normal = Qt.rect(x, y, width, height)
        maximized = visibility === Window.Maximized
        app.show_place(place)
    }
    onXChanged: placeTimer.restart()
    onYChanged: placeTimer.restart()
    onWidthChanged: placeTimer.restart()
    onHeightChanged: placeTimer.restart()
    onVisibilityChanged: placeTimer.restart()
    onClosing: placeTimer.save()
    // The controller builds a place's data only while it shows.
    onPlaceChanged: app.show_place(place)
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

    // The place is written a moment after the last move or resize, not at every pixel of a drag, and on closing.
    Timer {
        id: placeTimer

        objectName: "placeTimer"
        interval: app.save_delay

        function save() {
            stop()
            if (window.visibility === Window.Windowed) {
                window.normal = Qt.rect(window.x, window.y, window.width, window.height)
                window.maximized = false
            } else if (window.visibility === Window.Maximized) {
                window.maximized = true
            }
            app.save_window_state(window.normal.x, window.normal.y, window.normal.width, window.normal.height,
                                  window.maximized)
        }

        onTriggered: save()
    }

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

                // While files of the open place are read the workspace is disabled, which keeps keys out, and covered.
                Home {
                    id: home

                    anchors.fill: parent
                    enabled: !app.reading_open_batch
                    visible: !app.loaded
                }

                Workspace {
                    anchors.fill: parent
                    enabled: !app.reading_open_batch
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

                LoadingOverlay {
                    objectName: "loadingOverlay"
                    anchors.fill: parent
                    visible: app.reading_open_batch
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

    // Discard changes: the question names the place and what goes; the answer is final.
    ConfirmPopup {
        id: discard

        objectName: "discardPopup"
        heading: app.discard_question.heading
        text: app.discard_question.text
        yes: app.discard_question.yes
        danger: true
        onAccepted: app.discard_changes()
    }

    Connections {
        target: app

        function onDiscard_asked() {
            discard.open()
        }
    }

    LanguageDialog {}

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
