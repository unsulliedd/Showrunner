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
                anchors.right: parent.right
                anchors.rightMargin: Theme.space_md
                anchors.verticalCenter: parent.verticalCenter
                iconName: "plus"
                label: Strings.t("library.add")
                onClicked: app.choose_folder()
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
            delegate: LibraryRow {}

            ScrollBar.vertical: Scroller {}

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
