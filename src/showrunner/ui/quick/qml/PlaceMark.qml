import QtQuick
import Showrunner

// Where a track choice comes from: "From the show" when a place above made it, "Overrides the show" when the open
// place's own choice stands over one it receives. `choice` is a chip, a matrix column or a movie card from the
// controller; the mark is empty, and hidden, for a choice made here with nothing above it. `brief` takes the brief
// form ("From show") for a narrow matrix column.
UiText {
    required property var choice
    property bool brief: false

    visible: text !== ""
    text: (brief ? choice.short : choice.from || choice.over) || ""
    color: choice.over ? Theme.control : Theme.faint
    font.pixelSize: Theme.text_xs
    elide: Text.ElideRight
}
