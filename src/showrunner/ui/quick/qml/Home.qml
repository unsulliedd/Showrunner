import QtQuick
import QtQuick.Layouts
import Showrunner

// The first screen, while nothing is loaded: the drop area with the two ways to choose, then the programs and the
// folders opened before.
Panel {
    id: home

    property bool dropping: false

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Theme.space_lg + Theme.space_sm
        spacing: Theme.space_xl + Theme.space_xs

        Item {
            Layout.fillWidth: true
            Layout.fillHeight: true

            DashedFrame {
                anchors.fill: parent
                stroke: home.dropping ? Theme.control : Theme.line_strong
            }

            Row {
                anchors.centerIn: parent
                spacing: Theme.space_2xl + Theme.space_xl

                HomeArt {
                    anchors.verticalCenter: parent.verticalCenter
                    width: Math.min(Theme.home_art_width, home.width / 4)
                    height: width / 2
                }

                Column {
                    anchors.verticalCenter: parent.verticalCenter
                    width: Math.min(Theme.home_text_width, home.width / 2)
                    spacing: Theme.space_lg

                    UiText {
                        width: parent.width
                        text: Strings.t("home.title")
                        wrapMode: Text.WordWrap
                        font.pixelSize: Theme.text_3xl
                        font.weight: Font.Bold
                    }

                    UiText {
                        width: parent.width
                        text: Strings.t("home.lead")
                        wrapMode: Text.WordWrap
                        color: Theme.muted
                        font.pixelSize: Theme.text_lg
                        lineHeight: 1.35
                    }

                    Item {
                        width: Theme.stroke
                        height: Theme.space_xs
                    }

                    Row {
                        spacing: Theme.space_md + Theme.space_xs

                        ActionButton {
                            kind: "primary"
                            size: Theme.row_lg + Theme.space_xs
                            iconName: "folder"
                            text: Strings.t("home.choose_folder")
                            onClicked: app.choose_folder()
                        }

                        ActionButton {
                            kind: "outline"
                            size: Theme.row_lg + Theme.space_xs
                            text: Strings.t("home.choose_files")
                            onClicked: app.choose_files()
                        }

                        UiText {
                            anchors.verticalCenter: parent.verticalCenter
                            text: Strings.t("home.or_drop")
                            color: Theme.faint
                        }
                    }
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            // The cards fill this row, which would otherwise make the row compete with the drop area for height.
            Layout.fillHeight: false
            Layout.preferredHeight: Theme.home_card_height
            spacing: Theme.space_lg

            Card {
                Layout.fillWidth: true
                Layout.fillHeight: true
                title: Strings.t("home.programs")

                Repeater {
                    model: app.programs

                    delegate: ProgramRow {}
                }
            }

            Card {
                Layout.fillWidth: true
                Layout.fillHeight: true
                title: Strings.t("home.recent")

                UiText {
                    visible: app.recent.length === 0
                    text: Strings.t("home.recent_empty")
                    color: Theme.faint
                }

                Repeater {
                    model: app.recent

                    delegate: RecentRow {}
                }
            }
        }
    }
}
