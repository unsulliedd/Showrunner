import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import Showrunner

// Overview of a movie: its video line, its audio and subtitle tracks as cards side by side, and the bar that says
// the choices are this movie's until saved to a profile.
Item {
    id: movie

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Theme.space_lg
        spacing: Theme.space_lg

        Rectangle {
            Layout.fillWidth: true
            implicitHeight: Theme.row_lg + Theme.space_md
            radius: Theme.radius_lg
            color: Theme.panel
            border.width: Theme.stroke
            border.color: Theme.line

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: Theme.space_lg
                anchors.rightMargin: Theme.space_lg
                spacing: Theme.space_md

                Icon {
                    name: "video"
                    size: Theme.icon_sm
                }

                UiText {
                    Layout.fillWidth: true
                    text: app.movie.video
                    font.weight: Font.Medium
                }

                UiText {
                    text: Strings.t("movie.video_kept")
                    color: Theme.faint
                    font.pixelSize: Theme.text_sm
                }
            }
        }

        ScrollView {
            id: scroll

            Layout.fillWidth: true
            Layout.fillHeight: true
            contentWidth: availableWidth
            clip: true

            RowLayout {
                width: scroll.availableWidth
                spacing: Theme.space_lg

                Repeater {
                    model: app.movie.groups

                    delegate: ColumnLayout {
                        required property var modelData

                        Layout.fillWidth: true
                        Layout.preferredWidth: 1
                        Layout.alignment: Qt.AlignTop
                        spacing: Theme.space_md

                        Row {
                            spacing: Theme.space_md

                            Icon {
                                anchors.verticalCenter: parent.verticalCenter
                                name: modelData.icon
                                size: Theme.icon_sm
                                color: Theme.muted
                            }

                            UiText {
                                anchors.verticalCenter: parent.verticalCenter
                                text: modelData.label
                                font.weight: Font.DemiBold
                            }

                            UiText {
                                anchors.verticalCenter: parent.verticalCenter
                                text: modelData.count
                                color: Theme.muted
                                font.pixelSize: Theme.text_sm
                            }
                        }

                        Repeater {
                            model: modelData.cards

                            delegate: TrackCard {
                                required property var modelData

                                Layout.fillWidth: true
                                track: modelData
                            }
                        }
                    }
                }
            }
        }

        SaveBar {
            Layout.fillWidth: true
            title: Strings.t("movie.bar.title")
            lead: Strings.t("movie.bar.lead")
        }
    }
}
