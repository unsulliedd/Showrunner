import QtQuick
import QtQuick.Layouts
import Showrunner

// The selected batch: its header with the facts and Exclude, then its places as tabs, each with its count.
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

                // The title, then the facts beside it; when both do not fit, the facts go under the title. Each
                // elides rather than run under Exclude.
                Row {
                    id: titleRow

                    readonly property bool besides: title.implicitWidth + spacing + factsBeside.implicitWidth <= heading.width

                    spacing: Theme.space_md + Theme.space_xs

                    UiText {
                        id: title

                        width: Math.min(implicitWidth, heading.width)
                        text: app.batch.title
                        font.pixelSize: Theme.text_2xl
                        font.weight: Font.Bold
                    }

                    UiText {
                        id: factsBeside

                        objectName: "factsBeside"
                        anchors.baseline: title.baseline
                        visible: titleRow.besides
                        text: app.batch.facts
                        color: Theme.muted
                    }
                }

                UiText {
                    objectName: "factsUnder"
                    width: Math.min(implicitWidth, heading.width)
                    visible: !titleRow.besides && text !== ""
                    text: app.batch.facts
                    color: Theme.muted
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

            HelpTip {
                objectName: "discardTip"
                Layout.alignment: Qt.AlignTop
                Layout.topMargin: (Theme.row_md - Theme.help_chip) / 2
                visible: workspace.place === "review"
                topic: "discard"
            }

            ActionButton {
                objectName: "excludeBatch"
                Layout.alignment: Qt.AlignTop
                kind: app.place_excluded ? "outline" : "ghost"
                iconName: app.place_excluded ? "" : "no_entry"
                text: app.place_excluded ? Strings.t("workspace.include") : Strings.t("workspace.exclude")
                Accessible.description: app.place_excluded ? Strings.t("workspace.include_help") : Strings.t("workspace.exclude_help")
                enabled: !app.locked
                onClicked: app.exclude_place(!app.place_excluded)
            }

            HelpTip {
                objectName: "excludeTip"
                Layout.alignment: Qt.AlignTop
                Layout.topMargin: (Theme.row_md - Theme.help_chip) / 2
                topic: "exclude"
            }
        }

        Tabs {
            Layout.fillWidth: true
            Layout.topMargin: Theme.space_md
            Layout.leftMargin: Theme.space_lg + Theme.space_sm
            Layout.rightMargin: Theme.space_lg + Theme.space_sm
            model: app.workspace_tabs.map(tab => Object.assign({}, tab, {
                label: Strings.t("workspace.tab." + tab.key),
                tip: tab.later ? "" : Strings.t("workspace.tab_tip." + tab.key)
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

        // A place that keeps its files as they are, or lies in one: nothing from above reaches it.
        RowLayout {
            objectName: "keptLine"
            Layout.fillWidth: true
            Layout.leftMargin: Theme.space_lg + Theme.space_sm
            Layout.rightMargin: Theme.space_lg
            Layout.topMargin: Theme.space_md
            visible: app.kept_text !== ""
            spacing: Theme.space_md

            Icon {
                name: "check"
                size: Theme.icon_sm
                color: Theme.control
            }

            UiText {
                Layout.fillWidth: true
                text: app.kept_text
                color: Theme.muted
                font.pixelSize: Theme.text_sm
                wrapMode: Text.WordWrap
            }

            HelpTip {
                objectName: "keepTip"
                topic: "keep"
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

            Subtitles {
                anchors.fill: parent
                visible: workspace.place === "subtitles"
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
