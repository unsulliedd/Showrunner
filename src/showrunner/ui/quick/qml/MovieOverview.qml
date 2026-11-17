import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import Showrunner

// Overview of a movie: its video line, its audio and subtitle tracks as cards side by side, and the bar that says
// the choices are this movie's until saved to a profile. The cards of a kind stand in the order of the tracks in the
// new file; a card's grip moves it among them.
Item {
    id: movie

    // Read once: each read of the property converts the movie's cards for QML.
    readonly property var view: app.movie
    // The card a grip drags (its column) and how many places it has gone, for the line that shows where it lands.
    property int dragFrom: -1
    property int dragPlaces: 0

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
                    text: movie.view.video
                    font.weight: Font.Medium
                }

                UiText {
                    text: Strings.t("movie.video_kept")
                    color: Theme.faint
                    font.pixelSize: Theme.text_sm
                }
            }
        }

        ScrollPane {
            id: scroll

            Layout.fillWidth: true
            Layout.fillHeight: true
            contentWidth: availableWidth
            clip: true

            // The view stays put while a card is dragged, so the drag moves the card, not the view.
            Binding {
                target: scroll.contentItem
                property: "interactive"
                value: movie.dragFrom < 0
            }

            RowLayout {
                width: scroll.availableWidth
                spacing: Theme.space_lg

                // Counts, not the lists: a move then updates the cards in place, and the focus can follow the moved
                // card to its new place.
                Repeater {
                    model: movie.view.groups.length

                    delegate: ColumnLayout {
                        id: group

                        required property int index
                        readonly property var modelData: movie.view.groups[index]
                        readonly property var cards: modelData.cards
                        // Where the dragged card lands, as a column, when it is one of this kind's.
                        readonly property int dragged: cards.findIndex(c => c.id === movie.dragFrom)
                        readonly property int to: dragged < 0 ? -1
                                                  : cards[Math.max(0, Math.min(cards.length - 1,
                                                                               dragged + movie.dragPlaces))].id

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
                            id: cardRepeater

                            model: group.cards.length

                            delegate: TrackCard {
                                required property int index

                                Layout.fillWidth: true
                                track: group.cards[index]
                                landing: group.to !== track.id || group.to === movie.dragFrom ? ""
                                       : group.to < movie.dragFrom ? "before" : "after"
                                onDraggedChanged: {
                                    movie.dragFrom = dragged ? track.id : -1
                                    movie.dragPlaces = 0
                                }
                                onDragPlacesChanged: if (dragged) movie.dragPlaces = dragPlaces
                                onMoveBy: places => {
                                    const focused = grip.activeFocus
                                    const at = app.move_track(track.id, track.id + places)
                                    const moved = group.cards.findIndex(c => c.id === at)
                                    if (focused && moved >= 0)
                                        cardRepeater.itemAt(moved).grip.forceActiveFocus()
                                }
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
