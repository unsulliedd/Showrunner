import QtQuick
import Showrunner

// The drawing beside the home screen's title: two video cards with their tracks, one kept, one added and one
// dropped, and the drop mark in front.
Item {
    id: art

    readonly property real unit: width / 24

    implicitWidth: Theme.home_art_width
    implicitHeight: Theme.home_art_width / 2

    component Card: Rectangle {
        id: card

        property var chips: []

        width: art.unit * 13.5
        height: art.unit * 8.5
        radius: Theme.radius_lg
        color: Theme.panel_2
        border.width: Theme.stroke
        border.color: Theme.line_strong
        antialiasing: true

        Column {
            x: art.unit
            y: art.unit
            spacing: art.unit * 0.7

            Row {
                spacing: art.unit * 0.7

                Icon {
                    name: "film"
                    size: art.unit * 1.1
                }

                Rectangle {
                    anchors.verticalCenter: parent.verticalCenter
                    width: art.unit * 7
                    height: art.unit * 0.45
                    radius: height / 2
                    color: Theme.panel_3
                }
            }

            Repeater {
                model: card.chips

                delegate: Row {
                    required property var modelData

                    spacing: art.unit * 0.7

                    Rectangle {
                        width: art.unit * 1.8
                        height: art.unit * 1.1
                        radius: Theme.radius_sm
                        color: Theme.panel_3
                        border.width: Theme.stroke
                        border.color: modelData.color

                        UiText {
                            anchors.centerIn: parent
                            mono: true
                            text: modelData.code
                            color: modelData.color === Theme.line_strong ? Theme.ink : modelData.color
                            font.pixelSize: art.unit * 0.6
                            font.weight: Font.Medium
                            font.strikeout: modelData.color === Theme.drop
                        }
                    }

                    Rectangle {
                        anchors.verticalCenter: parent.verticalCenter
                        width: art.unit * 5
                        height: art.unit * 0.45
                        radius: height / 2
                        color: Theme.panel_3
                    }
                }
            }
        }
    }

    Card {
        x: art.unit * 1.5
        y: art.unit * 3
        rotation: -6
        opacity: 0.85
        chips: [
            { code: Strings.t("home.art.kept"), color: Theme.line_strong },
            { code: Strings.t("home.art.added"), color: Theme.line_strong },
            { code: Strings.t("home.art.kept"), color: Theme.line_strong }
        ]
    }

    Card {
        x: art.unit * 9
        y: art.unit * 0.8
        rotation: 4
        chips: [
            { code: Strings.t("home.art.kept"), color: Theme.line_strong },
            { code: Strings.t("home.art.added"), color: Theme.add },
            { code: Strings.t("home.art.kept"), color: Theme.drop }
        ]
    }

    Rectangle {
        x: art.unit * 15.2
        y: art.unit * 7.6
        width: art.unit * 3.4
        height: width
        radius: Theme.radius_lg
        color: Theme.control

        Icon {
            anchors.centerIn: parent
            name: "upload"
            size: art.unit * 1.6
            color: Theme.control_ink
        }
    }
}
