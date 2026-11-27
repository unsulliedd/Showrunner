import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import Showrunner

// The library on the left: the Library and Files tabs, the filter, the tree, and a place to drop more folders.
Panel {
    id: panel

    property string tab: "library"

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Theme.stroke
        spacing: 0

        Item {
            Layout.fillWidth: true
            Layout.preferredHeight: Theme.workspace_tabs

            Tabs {
                anchors.fill: parent
                anchors.leftMargin: Theme.space_sm
                model: [
                    { key: "library", label: Strings.t("library.tab.library") },
                    { key: "files", label: Strings.t("library.tab.files") }
                ]
                current: panel.tab
                onPicked: key => panel.tab = key
            }

            IconButton {
                id: add

                anchors.right: parent.right
                anchors.rightMargin: Theme.space_md
                anchors.verticalCenter: parent.verticalCenter
                iconName: "plus"
                label: Strings.t("library.add")
                tip: Strings.t("tip.library_add")
                onClicked: app.choose_folder()
            }

            // Reads the open folders again, under the same rule as Close.
            IconButton {
                id: refresh

                objectName: "refreshLibrary"
                anchors.right: add.left
                anchors.rightMargin: Theme.space_xs
                anchors.verticalCenter: parent.verticalCenter
                visible: app.loaded
                enabled: app.can_change_library
                iconName: "refresh"
                label: Strings.t("library.refresh")
                tip: Strings.t("tip.library_refresh")
                onClicked: app.refresh_library()
            }

            // Back to Home; a library being read, applied or read again after a job is not closed under its job.
            IconButton {
                objectName: "closeFolder"
                anchors.right: refresh.left
                anchors.rightMargin: Theme.space_xs
                anchors.verticalCenter: parent.verticalCenter
                visible: app.loaded
                enabled: app.can_change_library
                iconName: "x"
                label: Strings.t("library.close_all")
                ToolTip.visible: hovered
                ToolTip.text: label
                onClicked: app.close_folder()
            }
        }

        RowLayout {
            Layout.fillWidth: true
            Layout.margins: Theme.space_md + Theme.space_xs
            Layout.bottomMargin: Theme.space_sm
            visible: app.loaded && panel.tab === "library"
            spacing: Theme.space_sm + Theme.space_xs

            FindField {
                Layout.fillWidth: true
                placeholderText: Strings.t("library.filter_short")
                text: app.filter_text
                onTextEdited: app.filter_text = text
            }

            ActionButton {
                visible: app.needs_look > 0
                kind: "outline"
                iconName: "alert"
                text: app.needs_look
                checkable: true
                Accessible.name: Strings.f("library.needs_look", { count: app.needs_look })
                Accessible.description: Strings.t("library.needs_look_tip")
                ToolTip.visible: hovered
                ToolTip.text: Accessible.description
                onToggled: app.needs_look_only = checked
            }
        }

        TreeView {
            id: tree

            objectName: "libraryTree"

            Layout.fillWidth: true
            Layout.fillHeight: true
            visible: app.loaded && panel.tab === "library"
            clip: true
            model: app.library
            boundsBehavior: Flickable.StopAtBounds
            // Tab reaches the tree; Menu or Shift+F10 opens the menu of the selected row.
            activeFocusOnTab: true
            delegate: LibraryRow {
                id: item

                onMenuAsked: (x, y) => menu.popup(item, x, y)
            }

            ScrollBar.vertical: Scroller {}

            function openMenu() {
                const row = tree.itemAtIndex(app.selected_index)
                if (row !== null)
                    menu.popup(row, row.width / 2, row.height)
            }

            Keys.onMenuPressed: openMenu()
            Keys.onPressed: event => {
                if (event.key === Qt.Key_F10 && (event.modifiers & Qt.ShiftModifier)) {
                    openMenu()
                    event.accepted = true
                }
            }

            function reveal() {
                const index = app.selected_index
                if (!index.valid)
                    return
                tree.expandToIndex(index)
                tree.forceLayout()
                tree.positionViewAtIndex(index, TableView.Contain)
            }

            Connections {
                target: app

                // Shows and the movies open one level; the path to the selection opens all the way.
                function onLibrary_changed() {
                    tree.expandRecursively(-1, 1)
                    tree.reveal()
                }

                function onBatch_changed() {
                    tree.reveal()
                }
            }
        }

        ActionMenu {
            id: menu

            objectName: "libraryMenu"
            actions: app.place_actions
            onPicked: key => app.place_action(key)
        }

        Placeholder {
            Layout.fillWidth: true
            Layout.fillHeight: true
            visible: !app.loaded && panel.tab === "library"
            iconName: "folder"
            title: Strings.t("library.empty.title")
            lead: Strings.t("library.empty.lead")
        }

        Placeholder {
            Layout.fillWidth: true
            Layout.fillHeight: true
            visible: panel.tab === "files"
            iconName: "list"
            title: Strings.t("library.files.title")
            lead: Strings.t("library.files.lead")
        }

        AbstractButton {
            id: drop

            Layout.fillWidth: true
            Layout.margins: Theme.space_md + Theme.space_xs
            Layout.preferredHeight: Theme.row_lg + Theme.space_xs
            visible: app.loaded
            hoverEnabled: true
            Accessible.role: Accessible.Button
            Accessible.name: Strings.t("library.drop")
            onClicked: app.choose_folder()

            background: DashedFrame {
                radius: Theme.radius_md
                stroke: drop.hovered ? Theme.control : Theme.line_strong
            }

            contentItem: Item {
                Row {
                    anchors.centerIn: parent
                    spacing: Theme.space_md

                    Icon {
                        anchors.verticalCenter: parent.verticalCenter
                        name: "upload"
                        size: Theme.icon_sm
                    }

                    UiText {
                        anchors.verticalCenter: parent.verticalCenter
                        text: Strings.t("library.drop")
                        color: Theme.muted
                    }
                }
            }
        }
    }
}
