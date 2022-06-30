"""medford_syntax.py

By: Liam Strand
On: June 2022

Provides a LSP-compatable interface into the medford parser. Only currently
supports reporting on syntax errors.
"""

import re
from typing import List, Optional, Tuple

from MEDFORD.medford_detail import detail, detail_return
from MEDFORD.medford_error_mngr import (
    error_mngr,
    mfd_duplicated_macro,
    mfd_no_desc,
    mfd_remaining_template,
    mfd_syntax_err,
    mfd_unexpected_macro,
    mfd_wrong_macro_token,
)
from pygls.lsp.types import (
    Diagnostic,
    DiagnosticRelatedInformation,
    DiagnosticSeverity,
    Location,
    Position,
    Range,
)
from pygls.workspace import Document


def validate_syntax(
    text_doc: Document,
) -> Tuple[List[detail], List[Diagnostic]]:
    """Evaluates the syntax of a medford file and generates a token list and
    diagnostic list
    Parameters: A text document reference
    Returns: A tuple containing the tokens and the diagnostics
    Effects: None
    """
    source = text_doc.source.splitlines()

    details = []
    diagnostics = []

    # The medford parser's macro dict is not reset or reinitilized
    # when the parser starts, so we take care of that here.
    detail.macro_dictionary = {}

    # Set up the error manager
    err_mngr = error_mngr("ALL", "LINE")

    # Tokenize the document
    detail_ret = None
    for line_num, line in enumerate(source):
        if line.strip() != "":
            detail_ret = detail.FromLine(line, line_num + 1, detail_ret, err_mngr)
            if isinstance(detail_ret, detail_return):
                if detail_ret.is_novel:
                    details.append(detail_ret.detail)

    # Convert the medford parser format errors into LSP format Diagnostics
    # for err in err_mngr.get_syntax_errors_list():
    #     diag = _syntax_error_to_diagnostic(err, source, text_doc.uri)
    #     if diag:
    #         diagnostics.append(diag)
    for row in err_mngr._syntax_err_coll.values():
        for err in row:
            diag = _syntax_error_to_diagnostic(err, source, text_doc.uri)
            if diag:
                diagnostics.append(diag)

    # If something went really wrong, don't try to report a valid tokenization
    if err_mngr.has_major_parsing:
        details = []

    # Return both the tokenized file, and the diagnostics.
    return (details, diagnostics)


def _syntax_error_to_diagnostic(
    error: mfd_syntax_err, source: List[str], uri: str
) -> Optional[Diagnostic]:
    """Converts a medford parser format syntax error to a LSP diagnostic
    Parameters: A medford syntax error, the source document, and the document's uri
       Returns: A LSP Diagnostic containing the information in the syntax error
       Effects: None
    """
    # Extract critical information we are likely to use later
    line_number = error.lineno - 1
    error_type = error.errtype
    line_text = source[line_number]
    error_message = error.msg

    # For all non-specific syntax errors, or if the regexing fails, we
    # Start generating the Diagnostic
    diag = Diagnostic(
        # The first member, the range, describes the location of the syntax
        # error. It is comprised of two Positions, which are line:character
        # locations in a file.
        range=Range(
            # mark the entire line as an error.
            start=Position(line=line_number, character=0),
            end=Position(line=line_number + 1, character=0),
        ),
        # The severity for all of the messages are Error because they
        # make the MEDFORD file invalid.
        severity=DiagnosticSeverity.Error,
        # The error code is the same as the error_type because it is a unique
        # identifier to this kind of error.
        code=error_type,
        # The source tells the user where the error is coming from. In this
        # case, the error is coming from the MEDFORDness of the file.
        source="MEDFORD",
        # The error message is passed through to be presented to the user.
        message=error_message,
    )

    # For each error, we need to extract some information from the error message
    # generated by the medford parser. Then we generate a regular expression
    # that parses the erronious line and finds where in that line the error originates.

    # The Diagnostic object is deeply nested, documentation is in the LSP specification at
    # microsoft.github.io/language-server-protocol/specifications/lsp/3.17/specification/#diagnostic
    # and the actual python definition is at pygls/lsp/types/basic_structures.py on line 268.
    # Both of those resources have links to their nested objects.

    # If we were using python 3.10, we would us a match/case, but we need to
    # support 3.8+, so we use a big if elif block.

    # The other branches are very similar to this first one, so only this first
    # branch will be heavily documented. Other branches will be documented in their
    # novelty relative to this first branch
    if isinstance(error, mfd_unexpected_macro):

        # For most errors, we can extract the macro name from the error object
        macro = error.substr

        # Scan through the erronious line, looking for the macro's position
        match = re.search(f"(?:(?<=`@){macro}|(?<=`@{{){macro}(?=}}))", line_text)
        if match:
            diag.range = Range(
                start=Position(line=line_number, character=match.start()),
                end=Position(line=line_number, character=match.end()),
            )

    # Duplicated macros are a special case because we need to add some additional
    # information to the Diagnostic about the earlier definition of the macro.
    elif isinstance(error, mfd_duplicated_macro):
        macro = error.substr

        # Grab the line number that has the first instance of the macro
        # from the error object
        first_occourance = error.earlier_lineno - 1

        # For this error, we also look for the other occourance of the macro,
        # so that we can reference it in the Diagnostic.
        first_match = re.search(f"`@{macro}", source[first_occourance])
        second_match = re.search(f"`@{macro}", line_text)

        if first_match and second_match:
            diag.range = Range(
                start=Position(
                    line=first_occourance, character=first_match.start() + 2
                ),
                end=Position(line=first_occourance, character=first_match.end()),
            )

            # The related information points to the prior "probably correct"
            # macro definition.
            # fmt: off
            diag.related_information = [
                DiagnosticRelatedInformation(
                    location=Location(
                        uri=uri,
                        range=Range(
                            start=Position(
                                line=line_number, character=second_match.start()
                            ),
                            end=Position(
                                line=line_number, character=second_match.end()
                            ),
                        ),
                    ),
                    message="Earlier definition of macro",
                )
            ]
            # fmt: on
    elif isinstance(error, mfd_remaining_template):

        # This scan is much simpler because we only need to look for this
        # sequence of characters in the erronious line.
        match = re.search(r"\[..\]", line_text)
        if match:
            diag.range = Range(
                start=Position(line=line_number, character=match.start()),
                end=Position(line=line_number, character=match.end()),
            )
    elif isinstance(error, mfd_no_desc):
        match = re.search(f"@{error.substr}", line_text)
        if match:
            diag.range = Range(
                start=Position(line=line_number, character=match.start()),
                end=Position(line=line_number, character=match.end()),
            )
    elif isinstance(error, mfd_wrong_macro_token):
        match = re.search(r"'@", line_text)
        if match:
            diag.range = Range(
                start=Position(line=line_number, character=match.start()),
                end=Position(line=line_number, character=match.end()),
            )

    return diag