import QtQuick
import QtQuick.Layouts
import Showrunner

// The selected batch: its header with the facts and Leave out, then its places as tabs, each with its count.
Panel {
    id: workspace

    property string place: "overview"

    signal placePicked(string key)

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Theme.stroke
        spacing: 0

        RowLayout {
            Layout.fillWidth: true
            Layout.leftMargin: Theme.space_lg + Theme.space_sm
            Layout.rightMargin: Theme.space_lg
            Layout.topMargin: Theme.space_lg + Theme.space_sm
            spacing: Theme.space_lg + Theme.space_xs

            Rectangle {
                visible: app.batch_kind === "movie"
                Layout.preferredWidth: Theme.artwork_slot
                Layout.preferredHeight: Theme.artwork_slot
                radius: Theme.radius_md
                color: Theme.well
                border.width: Theme.stroke
                border.color: Theme.line_strong

                Column {
                    anchors.centerIn: parent
                    spacing: Theme.space_sm

                    Icon {
                        anchors.horizontalCenter: parent.horizontalCenter
                        name: "image"
                    }

                    UiText {
                        anchors.horizontalCenter: parent.horizontalCenter
                        text: Strings.t("workspace.artwork")
                        color: Theme.faint
                        font.pixelSize: Theme.text_xs
                    }
                }
            }

            Column {
                id: heading

                Layout.fillWidth: true
                spacing: Theme.space_xs

                UiText {
                    width: Math.min(implicitWidth, heading.width)
                    text: app.batch.over
                    color: Theme.muted
                }

                // The title, then the facts in what room is left; each elides rather than run under Leave out.
                Row {
                    id: titleRow

                    spacing: Theme.space_md + Theme.space_xs

                    UiText {
                        id: title

                        width: Math.min(implicitWidth, heading.width)
                        text: app.batch.title
                        font.pixelSize: Theme.text_2xl
                        font.weight: Font.Bold
                    }

                    UiText {
                        anchors.baseline: title.baseline
                        width: Math.max(0, Math.min(implicitWidth, heading.width - title.width - titleRow.spacing))
                        text: app.batch.facts
                        color: Theme.muted
                    }
                }
            }

            ActionButton {
                objectName: "discardBatch"
                Layout.alignment: Qt.AlignTop
                // On Review only, beside what a discard would change; the library's right-click menu offers it anywhere.
                visible: workspace.place === "review"
                kind: "ghost"
                text: Strings.t("workspace.discard")
                Accessible.description: Strings.t("workspace.discard_help")
                enabled: app.can_discard
                onClicked: app.ask_discard()
            }

            ActionButton {
                objectName: "leaveOutBatch"
                Layout.alignment: Qt.AlignTop
                kind: app.batch_left_out ? "outline" : "ghost"
                iconName: app.batch_left_out ? "" : "x"
                text: app.batch_left_out ? Strings.t("workspace.put_back") : Strings.t("workspace.leave_out")
                Accessible.description: Strings.t("workspace.leave_out_help")
                enabled: !app.locked
                onClicked: app.leave_out_batch()
            }
        }

        Tabs {
            Layout.fillWidth: true
            Layout.topMargin: Theme.space_md
            Layout.leftMargin: Theme.space_lg + Theme.space_sm
            Layout.rightMargin: Theme.space_lg + Theme.space_sm
            model: app.workspace_tabs.map(tab => Object.assign({}, tab, {
                label: Strings.t("workspace.tab." + tab.key)
            }))
            current: workspace.place
            onPicked: key => workspace.placePicked(key)
        }

        RowLayout {
            objectName: "lockLine"
            Layout.fillWidth: true
            Layout.leftMargin: Theme.space_lg + Theme.space_sm
            Layout.topMargin: Theme.space_md
            visible: app.locked
            spacing: Theme.space_md

            Icon {
                name: "lock"
                size: Theme.icon_sm
                color: Theme.muted
            }

            UiText {
                Layout.fillWidth: true
                text: Strings.t("workspace.locked")
                color: Theme.muted
                font.pixelSize: Theme.text_sm
            }
        }

        Item {
            Layout.fillWidth: true
            Layout.fillHeight: true
            // A batch being applied keeps its choices until the job ends; Review stays open to read.
            enabled: !app.locked || workspace.place === "review"

            Overview {
                anchors.fill: parent
                visible: workspace.place === "overview" && app.batch_kind !== "movie"
                onMatrixAsked: workspace.placePicked("tracks")
            }

            MovieOverview {
                anchors.fill: parent
                visible: workspace.place === "overview" && app.batch_kind === "movie"
            }

            Matrix {
                anchors.fill: parent
                visible: workspace.place === "tracks"
            }

            Names {
                anchors.fill: parent
                visible: workspace.place === "names"
            }

            Review {
                anchors.fill: parent
                visible: workspace.place === "review"
            }
        }
    }
}
