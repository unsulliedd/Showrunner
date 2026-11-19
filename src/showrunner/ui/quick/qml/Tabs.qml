import QtQuick
import QtQuick.Controls.Basic
import Showrunner

// A row of tabs over a hairline. Each entry of `model` has a `key` and `label`, and may have `icon`, `count` (-1 for
// none), `change` (false for a neutral count rather than an amber one), `later` (a place that does not exist yet)
// and `tip` (said under the tab on hover).
Item {
    id: tabs

    property var model: []
    property string current
    property int textSize: Theme.text_md

    signal picked(string key)

    implicitHeight: Theme.workspace_tabs
    implicitWidth: row.implicitWidth

    Rectangle {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        height: Theme.stroke
        color: Theme.line
    }

    Row {
        id: row

        height: parent.height
        spacing: Theme.space_xs

        Repeater {
            model: tabs.model

            delegate: Row {
                id: entry

                required property var modelData
                required property int index
                readonly property bool firstLater: modelData.later === true
                    && (index === 0 || tabs.model[index - 1].later !== true)

                height: row.height
                spacing: Theme.space_md
                // A place that does not exist yet and does not fit whole is left out rather than cut mid-word;
                // opacity rather than visible keeps its place in the row, so it comes back when the row widens.
                opacity: entry.modelData.later !== true || entry.x + entry.width <= tabs.width ? 1 : 0

                Rectangle {
                    visible: entry.firstLater
                    anchors.verticalCenter: parent.verticalCenter
                    width: Theme.stroke
                    height: Theme.text_lg
                    color: Theme.line_strong
                }

                AbstractButton {
                    id: tab

                    readonly property bool isCurrent: entry.modelData.key === tabs.current
                    readonly property bool later: entry.modelData.later === true

                    height: row.height
                    implicitWidth: content.implicitWidth + 2 * Theme.space_md
                    enabled: !later
                    hoverEnabled: true
                    focusPolicy: Qt.StrongFocus
                    Accessible.role: Accessible.PageTab
                    Accessible.name: entry.modelData.label
                    onClicked: tabs.picked(entry.modelData.key)

                    Tip {
                        visible: tab.hovered && (entry.modelData.tip ?? "") !== ""
                        text: entry.modelData.tip ?? ""
                    }

                    background: Item {
                        Rectangle {
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.bottom: parent.bottom
                            height: Theme.underline
                            color: tab.isCurrent ? Theme.control : tab.visualFocus ? Theme.line_strong : "transparent"
                        }
                    }

                    contentItem: Item {
                        implicitWidth: content.implicitWidth
                        implicitHeight: content.implicitHeight

                        Row {
                            id: content

                            anchors.centerIn: parent
                            spacing: Theme.space_md

                            Icon {
                                anchors.verticalCenter: parent.verticalCenter
                                visible: (entry.modelData.icon ?? "") !== ""
                                name: entry.modelData.icon ?? ""
                                size: Theme.icon_sm
                                color: tab.isCurrent ? Theme.ink : tab.later ? Theme.line_strong : Theme.faint
                            }

                            UiText {
                                anchors.verticalCenter: parent.verticalCenter
                                text: entry.modelData.label
                                font.pixelSize: tab.later ? Theme.text_sm : tabs.textSize
                                font.weight: tab.isCurrent ? Font.DemiBold : Font.Medium
                                color: tab.isCurrent ? Theme.ink : tab.later ? Theme.faint
                                     : tab.hovered ? Theme.ink : Theme.muted
                            }

                            Count {
                                anchors.verticalCenter: parent.verticalCenter
                                // A place that changes nothing shows no count; a plain number shows even 0.
                                visible: (entry.modelData.count ?? -1) > (entry.modelData.change === false ? -1 : 0)
                                value: entry.modelData.count ?? 0
                                change: entry.modelData.change !== false
                            }
                        }
                    }
                }
            }
        }
    }
}
