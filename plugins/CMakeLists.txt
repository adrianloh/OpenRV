#
# Custom (non-upstream) RV packages. Every sub-folder that has a CMakeLists.txt
# is built into <name>-<version>.rvpkg and installed with the bundled packages.
# To add a plugin: create plugins/<name>/ with PACKAGE, <name>.py and a CMakeLists.txt
# copied from any sibling. See plugins/README.md.
#

FILE(
  GLOB packages
  RELATIVE ${CMAKE_CURRENT_SOURCE_DIR}
  *
)
FOREACH(
  package
  ${packages}
)
  IF(EXISTS ${CMAKE_CURRENT_SOURCE_DIR}/${package}/CMakeLists.txt)
    ADD_SUBDIRECTORY(${package})
  ENDIF()
ENDFOREACH()
