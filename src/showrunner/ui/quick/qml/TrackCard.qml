import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import Showrunner

// One track of a movie: star and F set the flags, x drops it, Restore undoes every choice on it. A paired file
// not yet added is a dashed card that adds it. The grip moves the card in the track order of the new file: dragged,
// or with Ctrl+Up and Ctrl+Down.
Item {
    id: card

    required property var track
    readonly property bool dropped: track.state === "dropped"
    readonly property bool offered: track.state === "paired"
    readonly property alias grip: grip
    readonly property bool dragged: grip.active
    readonly property int dragPlaces: grip.places
    // "before" or "after" while a dragged card would land in this card's place, for the line that shows it.
    property string landing: ""

    signal moveBy(int places)

    implicitHeight: Theme.track_card
    z: grip.active ? 1 : 0
    // A lifted card sits a little to the side, so the card whose place it is over still shows.
    transform: Translate {
        x: grip.active ? Theme.space_md : 0
        y: grip.offset
    }

    Rectangle {
        objectName: "orderLine"
        visible: card.landing !== ""
        y: card.landing === "before" ? -(Theme.space_md + height) / 2 : card.height + (Theme.space_md - height) / 2
        width: parent.width
        height: 3 * Theme.stroke
        radius: height / 2
        color: Theme.control
    }

    Rectangle {
        anchors.fill: parent
        visible: !card.offered
        radius: Theme.radius_lg
        color: card.dropped ? Theme.drop_soft : Theme.panel_2
        border.width: Theme.stroke
        border.color: grip.active ? Theme.control
                    : card.dropped ? Theme.drop : card.track.state === "added" ? Theme.add : Theme.line
    }

    DashedFrame {
        anchors.fill: parent
        visible: card.offered
        radius: Theme.radius_lg
        stroke: Theme.line_strong
    }

    ActionButton {
        anchors.fill: parent
        anchors.leftMargin: grip.visible ? Theme.space_md + grip.width : 0
        visible: card.offered
        kind: "ghost"
        iconName: "plus"
        text: Strings.f("movie.add_paired", {"title": card.track.title, "code": card.track.code})
        onClicked: app.toggle_keep(card.track.id)
    }

    // Outside the row, so an offered card, which shows only its add button, can be moved as well.
    Grip {
        id: grip

        objectName: "cardGrip"
        anchors.left: parent.left
        anchors.leftMargin: Theme.space_md
        anchors.verticalCenter: parent.verticalCenter
        visible: card.track.movable
        vertical: true
        step: Theme.track_card + Theme.space_md
        label: Strings.f("tracks.order.card", {"track": card.track.code + " " + card.track.title})
        onMoved: places => card.moveBy(places)
    }

    RowLayout {
        anchors.fill: parent
        anchors.leftMargin: grip.visible ? 2 * Theme.space_md + grip.width : Theme.space_lg
        anchors.rightMargin: Theme.space_md
        visible: !card.offered
        spacing: Theme.space_lg

        CodeBadge {
            objectName: "cardBadge"
            code: card.track.code
            look: card.track.state
            changed: card.track.language_set !== ""
            pickable: true
            onPicked: app.pick_language(card.track.id)
        }

        ColumnLayout {
            Layout.fillWidth: true
            spacing: Theme.space_xs

            UiText {
                Layout.fillWidth: true
                text: card.track.title
                color: card.dropped ? Theme.drop : Theme.ink
                font.weight: Font.DemiBold
                font.strikeout: card.dropped
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: Theme.space_sm

                Icon {
                    visible: !card.dropped && card.track.name !== ""
                    name: "names"
                    size: Theme.icon_sm
                    color: card.track.renamed ? Theme.change : Theme.faint
                }

                UiText {
                    text: card.track.name
                    color: card.dropped ? Theme.drop : card.track.renamed ? Theme.change : Theme.muted
                    font.pixelSize: Theme.text_sm
                    font.strikeout: card.dropped
                }

                UiText {
                    Layout.fillWidth: true
                    visible: !card.dropped
                    text: card.track.was
                    color: Theme.faint
                    font.pixelSize: Theme.text_xs
                }
            }
        }

        PlaceMark {
            objectName: "placeMark"
            choice: card.track
        }

        FlagButton {
            visible: !card.dropped
            flag: "default"
            on: card.track.default
            held: card.track.is_default
            onClicked: app.toggle_flag(card.track.id, "default")
        }

        FlagButton {
            visible: !card.dropped
            flag: "forced"
            on: card.track.forced
            held: card.track.is_forced
            onClicked: app.toggle_flag(card.track.id, "forced")
        }

        IconButton {
            visible: !card.dropped
            implicitWidth: Theme.row_sm
            implicitHeight: Theme.row_sm
            iconName: "x"
            label: Strings.t("tracks.drop")
            onClicked: app.toggle_keep(card.track.id)
        }

        ActionButton {
            visible: card.dropped
            text: Strings.t("tracks.restore")
            onClicked: app.restore(card.track.id)
        }
    }
}
