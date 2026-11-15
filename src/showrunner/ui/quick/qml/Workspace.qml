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
                Layout.fillWidth: true
                spacing: Theme.space_xs

                UiText {
                    text: app.batch.over
                    color: Theme.muted
                }

                Row {
                    spacing: Theme.space_md + Theme.space_xs

                    UiText {
                        id: title

                        text: app.batch.title
                        font.pixelSize: Theme.text_2xl
                        font.weight: Font.Bold
                    }

                    UiText {
                        anchors.baseline: title.baseline
                        text: app.batch.facts
                        color: Theme.muted
                    }
                }
            }

            ActionButton {
                Layout.alignment: Qt.AlignTop
                kind: "ghost"
                iconName: "x"
                text: Strings.t("workspace.leave_out")
                // Leaving a batch out of the run comes with Review.
                enabled: false
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

        Item {
            Layout.fillWidth: true
            Layout.fillHeight: true

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

            Placeholder {
                anchors.fill: parent
                visible: workspace.place === "review"
                title: Strings.t("workspace.placeholder." + workspace.place + ".title")
                lead: Strings.t("workspace.placeholder." + workspace.place + ".lead")
            }
        }
    }
}
