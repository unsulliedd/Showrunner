import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import Showrunner

// The drawer's Jobs tab: the job's progress and Cancel, then each file with its steps as the stage runs them
// (the active one with its percentage), and once a file ends what was done or why not, the remux check included.
Item {
    id: panel

    readonly property var job: app.jobs.view

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Theme.space_lg
        spacing: Theme.space_md

        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.space_lg

            ColumnLayout {
                Layout.fillWidth: true
                spacing: Theme.space_sm

                Row {
                    spacing: Theme.space_md

                    UiText {
                        text: panel.job.title || ""
                        font.weight: Font.Bold
                    }

                    UiText {
                        text: panel.job.started || ""
                        color: Theme.muted
                        font.pixelSize: Theme.text_sm
                    }
                }

                RowLayout {
                    spacing: Theme.space_lg

                    ProgressLine {
                        Layout.preferredWidth: Theme.home_text_width
                        value: panel.job.fraction || 0
                        Accessible.name: panel.job.count || ""
                    }

                    UiText {
                        text: panel.job.line || ""
                        color: Theme.muted
                        font.pixelSize: Theme.text_sm
                    }
                }
            }

            Item {
                Layout.fillWidth: true
            }

            ActionButton {
                objectName: "jobCancel"
                visible: panel.job.running === true
                kind: "outline"
                iconName: "x"
                text: Strings.t("jobs.cancel")
                onClicked: app.jobs.cancel()
            }

            ActionButton {
                visible: panel.job.running === false
                kind: "ghost"
                text: Strings.t("jobs.clear")
                onClicked: app.jobs.clear()
            }
        }

        UiText {
            Layout.fillWidth: true
            visible: (panel.job.summary || "") !== ""
            text: panel.job.summary || ""
            font.weight: Font.Medium
            wrapMode: Text.WordWrap
        }

        ListView {
            id: rows

            objectName: "jobRows"
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            spacing: Theme.space_xs
            boundsBehavior: Flickable.StopAtBounds
            model: panel.job.rows || []
            // The list is rebuilt on every step; it follows the running file, or the first that failed.
            onModelChanged: if ((panel.job.active ?? -1) >= 0) positionViewAtIndex(panel.job.active, ListView.Contain)

            delegate: Rectangle {
                id: row

                required property var modelData

                width: rows.width
                implicitHeight: content.implicitHeight + 2 * Theme.space_md
                radius: Theme.radius_md
                color: modelData.state === "running" ? Theme.panel_2 : "transparent"
                border.width: modelData.state === "running" ? Theme.stroke : 0
                border.color: Theme.line_strong
                Accessible.role: Accessible.ListItem
                Accessible.name: modelData.title + " " + modelData.time

                ColumnLayout {
                    id: content

                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.margins: Theme.space_md
                    spacing: Theme.space_sm

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: Theme.space_lg

                        Row {
                            Layout.preferredWidth: Theme.matrix_label
                            spacing: Theme.space_md

                            Icon {
                                anchors.verticalCenter: parent.verticalCenter
                                visible: row.modelData.state !== "waiting"
                                name: row.modelData.state === "done" ? "check"
                                    : row.modelData.state === "running" ? "resume" : "alert"
                                size: Theme.icon_sm
                                color: row.modelData.state === "done" ? Theme.add
                                     : row.modelData.state === "running" ? Theme.control
                                     : row.modelData.state === "failed" ? Theme.drop : Theme.change
                            }

                            UiText {
                                anchors.verticalCenter: parent.verticalCenter
                                visible: row.modelData.number !== ""
                                mono: true
                                text: row.modelData.number
                                color: Theme.faint
                                font.pixelSize: Theme.text_xs
                            }

                            UiText {
                                anchors.verticalCenter: parent.verticalCenter
                                width: Theme.matrix_label - Theme.space_2xl - Theme.space_lg
                                text: row.modelData.title
                                font.weight: Font.Medium
                            }
                        }

                        Repeater {
                            model: row.modelData.phases

                            delegate: ColumnLayout {
                                required property var modelData

                                Layout.fillWidth: true
                                Layout.preferredWidth: 1
                                spacing: Theme.space_xs

                                RowLayout {
                                    Layout.fillWidth: true

                                    UiText {
                                        Layout.fillWidth: true
                                        text: modelData.label
                                        color: modelData.state === "waiting" || modelData.state === "skipped"
                                               ? Theme.faint : Theme.ink
                                        font.pixelSize: Theme.text_sm
                                        font.weight: modelData.state === "waiting" ? Font.Normal : Font.DemiBold
                                    }

                                    UiText {
                                        visible: modelData.percent >= 0
                                        text: Strings.f("jobs.percent", { percent: modelData.percent })
                                        color: Theme.control
                                        font.pixelSize: Theme.text_sm
                                        font.weight: Font.DemiBold
                                    }

                                    Icon {
                                        visible: modelData.state === "done" || modelData.state === "failed"
                                        name: modelData.state === "done" ? "check" : "x"
                                        size: Theme.icon_sm
                                        color: modelData.state === "done" ? Theme.add : Theme.drop
                                    }
                                }

                                ProgressLine {
                                    Layout.fillWidth: true
                                    value: modelData.state === "done" || modelData.state === "failed" ? 1
                                         : modelData.state === "active" ? Math.max(modelData.percent, 0) / 100 : 0
                                    fill: modelData.state === "done" ? Theme.add
                                        : modelData.state === "failed" ? Theme.drop : Theme.control
                                }
                            }
                        }

                        UiText {
                            Layout.preferredWidth: Theme.row_lg * 2
                            horizontalAlignment: Text.AlignRight
                            text: row.modelData.time
                            color: Theme.muted
                            font.pixelSize: Theme.text_sm
                        }
                    }

                    Repeater {
                        model: row.modelData.result

                        delegate: UiText {
                            required property var modelData

                            Layout.fillWidth: true
                            Layout.leftMargin: Theme.matrix_label + Theme.space_lg
                            text: modelData
                            color: row.modelData.state === "failed" ? Theme.drop : Theme.muted
                            font.pixelSize: Theme.text_sm
                            wrapMode: Text.WordWrap
                        }
                    }
                }
            }

            ScrollBar.vertical: ScrollBar {}
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.space_md

            Icon {
                name: "resume"
                size: Theme.icon_sm
                color: Theme.faint
            }

            UiText {
                Layout.fillWidth: true
                text: Strings.t("jobs.safety")
                color: Theme.muted
                font.pixelSize: Theme.text_sm
                wrapMode: Text.WordWrap
            }
        }
    }
}
