import QtQuick
import QtQuick.Controls.Basic
import Showrunner

// A scroll view whose scrollbar shows whenever the content is taller than the view, beside the content rather than
// over its right edge. A scroll view's bar is placed by hand, as the style places its own: attached by itself it
// sits in the top left corner. The bar's room is kept whether it shows or not: padding that followed the bar fed back
// into the layout (the padding sets the content's width, the width its height, the height whether the bar shows),
// which in one window never settled and hung it.
ScrollView {
    id: view

    rightPadding: bar.implicitWidth

    ScrollBar.vertical: Scroller {
        id: bar

        parent: view
        x: view.mirrored ? 0 : view.width - width
        y: view.topPadding
        height: view.availableHeight
    }
}
