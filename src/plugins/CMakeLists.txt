#
# Copyright (C) 2022  Autodesk, Inc. All Rights Reserved.
#
# SPDX-License-Identifier: Apache-2.0
#

ADD_SUBDIRECTORY(output)
ADD_SUBDIRECTORY(python)
ADD_SUBDIRECTORY(rv-packages)

# Custom packages (see /plugins)
ADD_SUBDIRECTORY(${PROJECT_SOURCE_DIR}/plugins ${CMAKE_CURRENT_BINARY_DIR}/custom-plugins)
