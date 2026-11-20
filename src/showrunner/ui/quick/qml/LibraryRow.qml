import QtQuick
import QtQuick.Controls.Basic
import Showrunner

// One row of the library tree: a show, a season, an episode, the extras of a show, an extra, the movies, or a movie.
AbstractButton {
    id: row

    required property TreeView treeView
    required property bool expanded
    required property bool hasChildren
    required property int depth
    required property int row
    required property int column
    required property string label
    required property string kind
    required property string number
    required property string summary
    required property string problem
    required property string problem_tip
    required property bool planned
    required property bool excluded
    required property bool kept
    required property string row_id

    readonly property bool isSelected: row_id === app.selected
    // What the mark at the row's end says: a file that needs a look, or changes planned at or below the row.
    readonly property string markTip: excluded ? "" : problem !== "" ? problem_tip : planned ? Strings.t("library.mark.planned") : ""

    // The row was right-clicked, at this point of the row; it is selected first, so the menu is that place's.
    signal menuAsked(real x, real y)
    readonly property bool isGroup: kind === "show" || kind === "movies"

    implicitWidth: treeView.width
    implicitHeight: Theme.row_md - Theme.space_xs
    hoverEnabled: true
    focusPolicy: Qt.NoFocus
    Accessible.role: Accessible.TreeItem
    Accessible.name: number !== "" ? number + " " + label : label
    Accessible.description: [excluded ? Strings.t("library.excluded_tip") : "", kept ? Strings.t("library.kept_tip") : "", markTip].filter(t => t !== "").join(" ")
    onClicked: app.select(treeView.index(row.row, row.column))
    onDoubleClicked: if (hasChildren) treeView.toggleExpanded(row.row)

    background: Rectangle {
        x: Theme.space_sm + Theme.space_xs
        width: parent.width - 2 * x
        radius: Theme.radius_md
        color: row.isSelected ? Theme.select : row.hovered ? Theme.panel_2 : "transparent"
        border.width: row.isSelected && row.treeView.activeFocus ? Theme.stroke : 0
        border.color: Theme.control
    }

    TapHandler {
        acceptedButtons: Qt.RightButton
        onTapped: point => {
            app.select(row.treeView.index(row.row, row.column))
            row.menuAsked(point.position.x, point.position.y)
        }
    }

    contentItem: Item {
        Icon {
            id: chevron

            x: Theme.space_lg + row.depth * Theme.space_lg
            anchors.verticalCenter: parent.verticalCenter
            visible: row.hasChildren
            name: row.expanded ? "down" : "right"
            size: Theme.icon_sm

            TapHandler {
                onTapped: row.treeView.toggleExpanded(row.row)
            }
        }

        Row {
            anchors.left: chevron.right
            anchors.leftMargin: Theme.space_md
            anchors.right: right.left
            anchors.rightMargin: Theme.space_md
            anchors.verticalCenter: parent.verticalCenter
            spacing: Theme.space_md

            Icon {
                anchors.verticalCenter: parent.verticalCenter
                visible: row.isGroup
                name: row.kind === "show" ? "tv" : "film"
                size: Theme.icon_sm
            }

            UiText {
                anchors.verticalCenter: parent.verticalCenter
                visible: row.number !== ""
                mono: true
                text: row.number
                color: Theme.faint
                font.pixelSize: Theme.text_xs
            }

            UiText {
                anchors.verticalCenter: parent.verticalCenter
                width: Math.min(implicitWidth, parent.width - x)
                text: row.label
                color: row.excluded ? Theme.faint : Theme.ink
                font.weight: row.isGroup ? Font.DemiBold : row.kind === "season" || row.kind === "extras" ? Font.Medium : Font.Normal
            }
        }

        Row {
            id: right

            anchors.right: parent.right
            anchors.rightMargin: Theme.space_lg + Theme.space_xs
            anchors.verticalCenter: parent.verticalCenter
            spacing: Theme.space_md

            Count {
                anchors.verticalCenter: parent.verticalCenter
                visible: row.kind === "show"
                value: Number(row.summary)
                change: false
            }

            UiText {
                anchors.verticalCenter: parent.verticalCenter
                visible: row.kind !== "show"
                mono: row.kind === "episode" || row.kind === "extra" || row.kind === "movie"
                text: row.summary
                color: Theme.faint
                font.pixelSize: mono ? Theme.text_xs : Theme.text_sm
            }

            // Excluded places carry the no-entry mark, dimmed with the row; the tooltip says what it means and how to
            // undo it.
            Icon {
                objectName: "excludedMark"
                anchors.verticalCenter: parent.verticalCenter
                visible: row.excluded
                name: "no_entry"
                size: Theme.icon_sm

                HoverHandler {
                    id: markHover
                }

                ToolTip.visible: markHover.hovered
                ToolTip.text: Strings.t("library.excluded_tip")
            }

            // A place that keeps its files as they are; the tooltip says so and how to undo it.
            Icon {
                objectName: "keptMark"
                anchors.verticalCenter: parent.verticalCenter
                visible: row.kept
                name: "check"
                size: Theme.icon_sm
                color: Theme.control

                HoverHandler {
                    id: keptHover
                }

                ToolTip.visible: keptHover.hovered
                ToolTip.text: Strings.t("library.kept_tip")
            }

            Item {
                objectName: "rowMark"
                anchors.verticalCenter: parent.verticalCenter
                width: Theme.icon_sm
                height: Theme.icon_sm
                visible: !row.excluded && (row.problem !== "" || row.planned)

                HoverHandler {
                    id: markTipHover
                }

                ToolTip.visible: markTipHover.hovered
                ToolTip.text: row.markTip

                Icon {
                    anchors.centerIn: parent
                    visible: row.problem !== ""
                    name: "alert"
                    size: Theme.icon_sm
                    color: row.problem === "drop" ? Theme.drop : Theme.change
                }

                Rectangle {
                    anchors.centerIn: parent
                    visible: row.problem === "" && row.planned
                    width: Theme.dot
                    height: Theme.dot
                    radius: Theme.dot / 2
                    color: Theme.change
                }
            }
        }
    }
}
